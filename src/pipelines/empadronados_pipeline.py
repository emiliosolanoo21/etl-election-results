"""Carga incremental del padrón para una fecha de corte (permite backfill)."""
from __future__ import annotations

from src.pipelines.base_pipeline import Pipeline
from src.pipelines.factory import build_pipeline


def build_empadronados_pipeline(fecha: str, force: bool = False) -> Pipeline:
    return build_pipeline("empadronados", fecha=fecha, force=force)
