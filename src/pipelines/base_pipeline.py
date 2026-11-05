"""Flujo genérico extract -> transform -> validate -> load, sin conocer fuente ni destino."""
from __future__ import annotations

import json
from datetime import datetime

from src.extractors.base import BaseExtractor
from src.loaders.base import BaseLoader
from src.quality.validations import Validator
from src.transformers.base import BaseTransformer
from src.utils.db import connect
from src.utils.logger import get_logger

logger = get_logger(__name__)


class QualityError(RuntimeError):
    pass


class RunRecorder:
    """Registra la ejecución en una conexión propia para que el error sobreviva al rollback."""

    def __init__(self, pipeline: str, context: dict) -> None:
        self.pipeline = pipeline
        self.context = context
        self.conn = connect()
        self.conn.autocommit = True
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO etl.ejecuciones (pipeline, fecha_proceso, archivo, hash_archivo, estado) "
                "VALUES (%s, %s, %s, %s, 'en_curso') RETURNING id_ejecucion",
                (pipeline, context.get("fecha_proceso"), context.get("archivo"), context.get("hash_archivo")),
            )
            self.id = cur.fetchone()[0]

    def quarantine(self, rejected: list[tuple[dict, str]]) -> None:
        rows = [(self.id, self.pipeline, self.context.get("fecha_proceso"), r.get("_linea"), rule,
                 json.dumps(r, default=str, ensure_ascii=False)) for r, rule in rejected]
        if rows:
            with self.conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO etl.cuarentena (id_ejecucion, pipeline, fecha_proceso, linea_origen, regla, registro) "
                    "VALUES (%s, %s, %s, %s, %s, %s)", rows)

    def finish(self, metrics: dict, error: str | None = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE etl.ejecuciones SET estado = %s, leidos = %s, transformados = %s, cargados = %s, "
                "rechazados = %s, detalle = %s, error = %s, fin = now(), segundos = %s WHERE id_ejecucion = %s",
                ("error" if error else "ok", metrics.get("leidos"), metrics.get("transformados"),
                 metrics.get("cargados"), metrics.get("rechazados"), json.dumps(metrics, default=str),
                 error, metrics.get("segundos"), self.id))
            cur.execute(
                "INSERT INTO electoral.carga_log (proceso, observacion, fecha) VALUES (%s, %s, %s)",
                (self.pipeline, (error or json.dumps({k: metrics.get(k) for k in ("leidos", "cargados", "rechazados")}))[:255],
                 datetime.now().isoformat(timespec="seconds")))
        self.conn.close()


class Pipeline:
    def __init__(self, extractor: BaseExtractor, transformer: BaseTransformer, loader: BaseLoader,
                 validator: Validator | None = None, name: str = "pipeline", context: dict | None = None,
                 on_reject: str = "quarantine", max_reject_ratio: float = 1.0, key: list[str] | None = None) -> None:
        self.extractor = extractor
        self.transformer = transformer
        self.loader = loader
        self.validator = validator
        self.name = name
        self.context = context or {}
        self.on_reject = on_reject
        self.max_reject_ratio = max_reject_ratio
        self.key = key or []

    def run(self) -> dict:
        started = datetime.now()
        logger.info("[%s] inicio %s", self.name, {k: v for k, v in self.context.items() if k != "hash_archivo"})
        recorder = RunRecorder(self.name, self.context)
        self.context["id_ejecucion"] = recorder.id
        metrics: dict = {"pipeline": self.name, "id_ejecucion": recorder.id}
        try:
            records = list(self.transformer.transform(self.extractor.extract()))
            metrics.update(leidos=getattr(self.extractor, "rows_read", None), transformados=len(records))
            rejected = []
            if self.validator:
                result = self.validator.run(records)
                records, rejected = result.valid, result.rejected
                metrics["calidad"] = result.summary
                self._handle_rejects(recorder, rejected, metrics)
            self.context["claves_rechazadas"] = [r.get(self.key[0]) for r, _ in rejected if self.key]
            metrics["cargados"] = self.loader.load(records, self.context)
            metrics["rechazados"] = len(rejected)
            metrics["carga"] = self.loader.stats
            metrics["segundos"] = round((datetime.now() - started).total_seconds(), 2)
            recorder.finish(metrics)
            logger.info("[%s] fin %s", self.name, json.dumps(metrics, default=str, ensure_ascii=False))
            return metrics
        except Exception as exc:
            metrics["segundos"] = round((datetime.now() - started).total_seconds(), 2)
            recorder.finish(metrics, error=f"{type(exc).__name__}: {exc}")
            logger.error("[%s] falló: %s", self.name, exc)
            raise

    def _handle_rejects(self, recorder: RunRecorder, rejected: list, metrics: dict) -> None:
        if not rejected:
            return
        ratio = len(rejected) / max(metrics["transformados"], 1)
        metrics["ratio_rechazo"] = round(ratio, 4)
        if self.on_reject == "fail" or ratio > self.max_reject_ratio:
            recorder.quarantine(rejected)
            raise QualityError(f"{len(rejected)} rechazos ({ratio:.1%}) superan el umbral; ver etl.cuarentena")
        if self.on_reject == "quarantine":
            recorder.quarantine(rejected)
            logger.warning("[%s] %s registros en etl.cuarentena: %s", self.name, len(rejected), metrics["calidad"]["por_regla"])
        else:
            logger.warning("[%s] %s registros descartados", self.name, len(rejected))
