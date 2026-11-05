"""Carga única: centros de votación y resultados históricos (con mesas derivadas)."""
from __future__ import annotations

from src.pipelines.base_pipeline import Pipeline
from src.pipelines.factory import build_pipeline


def build_centros_pipeline() -> Pipeline:
    return build_pipeline("centros_votacion")


def build_resultados_pipeline() -> Pipeline:
    return build_pipeline("resultados_historicos")
