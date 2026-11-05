"""Loaders de PostgreSQL: carga completa idempotente e incremental con watermark."""
from __future__ import annotations

from datetime import datetime

from psycopg2.extras import execute_values

from src.loaders.base import BaseLoader
from src.utils.db import insert_many
from src.utils.logger import get_logger

logger = get_logger(__name__)

MESAS_TABLE = "electoral.mesas_votacion"


def as_text(value):
    return None if value is None else str(value)


def to_rows(records: list[dict], columns: list[str], *extra) -> list[tuple]:
    return [tuple(as_text(r.get(c)) for c in columns) + extra for r in records]


def stage(conn, table: str, columns: list[str], rows: list[tuple]) -> str:
    """Crea una tabla temporal con la forma del destino y la llena."""
    staging = "stg_" + table.split(".")[-1]
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {staging}")
        cur.execute(f"CREATE TEMP TABLE {staging} (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
    insert_many(conn, staging, columns, rows)
    return staging


def sync_mesas(conn, records: list[dict]) -> int:
    """Deriva mesas desde los códigos presentes; solo inserta las que no existen."""
    mesas = {
        (r["codigo_mesa"], r["codigo_centro_votacion"], r["codigo_mesa"].split("-")[-1])
        for r in records if r.get("codigo_mesa") and r.get("codigo_centro_votacion")
    }
    if not mesas:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    sql = f"""
        INSERT INTO {MESAS_TABLE} (codigo_mesa, codigo_centro_votacion, numero_mesa, fechacarga)
        SELECT v.codigo_mesa, v.centro, v.numero, v.fecha
        FROM (VALUES %s) AS v(codigo_mesa, centro, numero, fecha)
        WHERE NOT EXISTS (SELECT 1 FROM {MESAS_TABLE} m WHERE m.codigo_mesa = v.codigo_mesa)
    """
    with conn.cursor() as cur:
        cur.execute(f"LOCK TABLE {MESAS_TABLE} IN SHARE ROW EXCLUSIVE MODE")
        execute_values(cur, sql, [m + (now,) for m in sorted(mesas)], page_size=1000)
        return cur.rowcount


class FullLoader(BaseLoader):
    """Staging + reemplazo atómico: reejecutar deja exactamente el mismo estado."""

    def __init__(self, table: str, natural_key: list[str], columns: list[str], derive_mesas: bool = False, **_) -> None:
        super().__init__(table, natural_key, columns)
        self.derive_mesas = derive_mesas

    def load_with(self, conn, records: list[dict], context: dict) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cols = self.columns + ["fechacarga"]
        staging = stage(conn, self.table, cols, to_rows(records, self.columns, now))
        with conn.cursor() as cur:
            cur.execute(f"LOCK TABLE {self.table} IN ACCESS EXCLUSIVE MODE")
            cur.execute(f"DELETE FROM {self.table}")
            borrados = cur.rowcount
            cur.execute(f"INSERT INTO {self.table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM {staging}")
            cargados = cur.rowcount
        self.stats = {"reemplazados": borrados, "cargados": cargados}
        if self.derive_mesas:
            self.stats["mesas_nuevas"] = sync_mesas(conn, records)
        logger.info("%s: %s", self.table, self.stats)
        return cargados


class IncrementalLoader(BaseLoader):
    """Upsert del padrón con detección de altas, traslados, bajas y ausencias."""

    def __init__(self, table: str, natural_key: list[str], columns: list[str], source: str = "empadronados",
                 absent_state: str = "baja_por_ausencia", derive_mesas: bool = False, **_) -> None:
        super().__init__(table, natural_key, columns)
        self.source = source
        self.absent_state = absent_state
        self.derive_mesas = derive_mesas

    def check_watermark(self, cur, fecha: str, force: bool) -> None:
        cur.execute("SELECT ultima_fecha FROM etl.watermark WHERE fuente = %s", (self.source,))
        row = cur.fetchone()
        if row and fecha < row[0].isoformat() and not force:
            raise RuntimeError(
                f"La fecha {fecha} es anterior al watermark {row[0]}: reprocesarla regresaría el padrón "
                "a un estado viejo. Use --force o reprocese en orden hasta la fecha actual."
            )

    def load_with(self, conn, records: list[dict], context: dict) -> int:
        fecha = context["fecha_proceso"]
        key = self.natural_key[0]
        protected = sorted(set(context.get("claves_rechazadas", [])))
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.source,))
            self.check_watermark(cur, fecha, context.get("force", False))
            staging = stage(conn, self.table, self.columns, to_rows(records, self.columns))
            self.stats = self._snapshot(cur, staging, fecha, protected)
            set_cols = [c for c in self.columns if c != key]
            cur.execute(f"""
                INSERT INTO {self.table} AS t ({', '.join(self.columns)})
                SELECT {', '.join(self.columns)} FROM {staging}
                ON CONFLICT ({key}) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in set_cols)}
                WHERE ({', '.join('t.' + c for c in set_cols)}) IS DISTINCT FROM ({', '.join('EXCLUDED.' + c for c in set_cols)})
                RETURNING (xmax = 0)
            """)
            flags = [row[0] for row in cur.fetchall()]
            self.stats["insertados"] = sum(flags)
            self.stats["actualizados"] = len(flags) - sum(flags)
            cur.execute(f"""
                UPDATE {self.table} SET estado_registro = %s, fecha_ultima_actualizacion = %s
                WHERE {key} NOT IN (SELECT {key} FROM {staging})
                  AND NOT ({key} = ANY(%s)) AND estado_registro IS DISTINCT FROM %s
            """, (self.absent_state, fecha, protected, self.absent_state))
            self.stats["marcados_ausentes"] = cur.rowcount
            if self.derive_mesas:
                self.stats["mesas_nuevas"] = sync_mesas(conn, records)
            cur.execute("""
                INSERT INTO etl.watermark (fuente, ultima_fecha, id_ejecucion) VALUES (%s, %s, %s)
                ON CONFLICT (fuente) DO UPDATE SET ultima_fecha = GREATEST(etl.watermark.ultima_fecha, EXCLUDED.ultima_fecha),
                    id_ejecucion = EXCLUDED.id_ejecucion, actualizado = now()
            """, (self.source, fecha, context.get("id_ejecucion")))
        logger.info("%s %s: %s", self.table, fecha, self.stats)
        return self.stats["insertados"] + self.stats["actualizados"]

    def _snapshot(self, cur, staging: str, fecha: str, protected: list[str]) -> dict:
        """Clasifica movimientos contra la fotografía del día anterior; es determinista al reprocesar."""
        cur.execute("DELETE FROM etl.empadronados_snapshot WHERE fecha_proceso = %s", (fecha,))
        prev = "(SELECT * FROM etl.empadronados_snapshot WHERE fecha_proceso = (SELECT max(fecha_proceso) FROM etl.empadronados_snapshot WHERE fecha_proceso < %(f)s))"
        cur.execute(f"""
            INSERT INTO etl.empadronados_snapshot
            SELECT %(f)s, s.id_empadronado, s.codigo_centro_votacion, s.codigo_mesa, s.estado_registro,
                CASE WHEN p.id_empadronado IS NULL THEN 'alta'
                     WHEN p.codigo_mesa IS DISTINCT FROM s.codigo_mesa THEN 'traslado'
                     WHEN p.estado_registro IS DISTINCT FROM s.estado_registro
                          AND s.estado_registro IN ('suspendido', 'fallecido') THEN 'baja'
                     WHEN p.estado_registro IS DISTINCT FROM s.estado_registro THEN 'cambio_estado'
                     ELSE 'sin_cambio' END
            FROM {staging} s LEFT JOIN {prev} p USING (id_empadronado)
        """, {"f": fecha})
        cur.execute(f"""
            INSERT INTO etl.empadronados_snapshot
            SELECT %(f)s, p.id_empadronado, p.codigo_centro_votacion, p.codigo_mesa, %(a)s, 'ausente'
            FROM {prev} p
            WHERE NOT EXISTS (SELECT 1 FROM {staging} s WHERE s.id_empadronado = p.id_empadronado)
              AND NOT (p.id_empadronado = ANY(%(protected)s)) AND p.estado_registro <> %(a)s
        """, {"f": fecha, "a": self.absent_state, "protected": protected})
        cur.execute("SELECT tipo_movimiento, count(*) FROM etl.empadronados_snapshot WHERE fecha_proceso = %s GROUP BY 1", (fecha,))
        return {"movimientos": dict(cur.fetchall())}
