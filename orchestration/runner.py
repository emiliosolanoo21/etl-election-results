"""Orquestador liviano: dependencias, reintentos con backoff, catch-up, backfill y alertas."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.settings import load_config, resolve_path, source_config  # noqa: E402
from src.pipelines.factory import build_pipeline  # noqa: E402
from src.utils.db import get_connection  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger("orchestration")

RETRIES = int(os.getenv("ETL_RETRIES", "3"))
BACKOFF_SECONDS = int(os.getenv("ETL_BACKOFF_SECONDS", "30"))


def alert(message: str) -> None:
    """Log de error y, si hay webhook configurado, aviso a Slack/Teams."""
    logger.error("ALERTA: %s", message)
    url = os.getenv("ALERT_WEBHOOK_URL")
    if url:
        body = json.dumps({"text": f"[ETL electoral] {message}"}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as exc:
            logger.error("No se pudo enviar la alerta: %s", exc)


def with_retries(task_name: str, fn, retries: int = RETRIES):
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except FileNotFoundError:
            raise
        except Exception as exc:
            logger.warning("[%s] intento %s/%s falló: %s", task_name, attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))


def last_ok(pipeline: str) -> bool:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM etl.ejecuciones WHERE pipeline = %s AND estado = 'ok' LIMIT 1", (pipeline,))
        return cur.fetchone() is not None


def watermark(source: str = "empadronados") -> date | None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT ultima_fecha FROM etl.watermark WHERE fuente = %s", (source,))
        row = cur.fetchone()
        return row[0] if row else None


def available_dates(source: str = "empadronados") -> list[date]:
    pattern = source_config(source)["extractor"]["path_pattern"]
    folder = resolve_path(pattern).parent
    prefix, suffix = Path(pattern).name.split("{fecha}")
    found = []
    for f in folder.glob(f"{prefix}*{suffix}"):
        stamp = f.name[len(prefix):-len(suffix)]
        found.append(date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])))
    return sorted(found)


def flow_historico(force: bool = False) -> None:
    """Carga única: respeta depends_on de config.yaml y no se repite si ya terminó bien."""
    order = ["centros_votacion", "resultados_historicos"]
    for name in order:
        if last_ok(name) and not force:
            logger.info("[%s] ya cargado; se omite (use --force para recargar)", name)
            continue
        with_retries(name, lambda n=name: build_pipeline(n).run())


def run_padron(fecha: date, force: bool = False) -> None:
    deps = source_config("empadronados").get("depends_on", [])
    missing = [d for d in deps if not last_ok(d)]
    if missing:
        raise RuntimeError(f"Dependencias sin carga exitosa: {missing}. Ejecute primero el flujo histórico.")
    with_retries(f"empadronados {fecha}", lambda: build_pipeline("empadronados", fecha.isoformat(), force).run())


def flow_diario(fecha: str | None = None) -> None:
    """Sin fecha procesa todos los días pendientes desde el watermark (catch-up)."""
    if fecha:
        pending = [date.fromisoformat(fecha)]
    else:
        wm = watermark()
        pending = [d for d in available_dates() if wm is None or d > wm]
    if not pending:
        logger.info("Padrón al día (watermark=%s)", watermark())
    for d in pending:
        run_padron(d)


def flow_backfill(desde: str, hasta: str) -> None:
    """Reprocesa un rango en orden; las fechas previas al watermark requieren force."""
    d, end = date.fromisoformat(desde), date.fromisoformat(hasta)
    available = set(available_dates())
    while d <= end:
        if d in available:
            run_padron(d, force=True)
        else:
            logger.warning("Sin archivo para %s; se omite", d)
        d += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Orquestación del ETL electoral")
    sub = parser.add_subparsers(dest="flow", required=True)
    h = sub.add_parser("historico")
    h.add_argument("--force", action="store_true")
    d = sub.add_parser("diario")
    d.add_argument("--fecha")
    b = sub.add_parser("backfill")
    b.add_argument("--desde", required=True)
    b.add_argument("--hasta", required=True)
    sub.add_parser("todo", help="Histórico y luego diario: útil para levantar todo desde cero")
    args = parser.parse_args()
    load_config()
    try:
        if args.flow == "historico":
            flow_historico(args.force)
        elif args.flow == "diario":
            flow_diario(args.fecha)
        elif args.flow == "backfill":
            flow_backfill(args.desde, args.hasta)
        else:
            flow_historico()
            flow_diario()
        return 0
    except Exception as exc:
        alert(f"Flujo '{args.flow}' falló definitivamente: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
