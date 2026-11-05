"""Construye un Pipeline a partir del bloque de config.yaml de una fuente."""
from __future__ import annotations

from datetime import date

from src.config.settings import load_config, resolve_path, source_config
from src.extractors.csv_extractor import CSVExtractor
from src.loaders.postgres_loader import FullLoader, IncrementalLoader
from src.pipelines.base_pipeline import Pipeline
from src.quality.validations import RULES, Validator
from src.transformers.base import TransformerPipeline
from src.transformers.common import (
    CanonicalByKey, CastNumeric, Deduplicate, EnrichFromCatalog, NormalizeText, ParseDates,
    RepairCentroFromMesa, StandardizeCategories, TrimStrings,
)
from src.utils import db

EXTRACTORS = {"csv": CSVExtractor}
LOADERS = {"full": FullLoader, "incremental": IncrementalLoader}


def build_transformer(spec: dict, cfg: dict):
    kind = spec["type"]
    if kind == "trim":
        return TrimStrings()
    if kind == "normalize_text":
        return NormalizeText(spec["fields"])
    if kind == "canonical_by_key":
        return CanonicalByKey(spec["field"], spec["key"])
    if kind == "cast_numeric":
        return CastNumeric(spec["fields"])
    if kind == "parse_dates":
        return ParseDates(spec["fields"], cfg.get("dates", {}).get("input_formats"))
    if kind == "categories":
        return StandardizeCategories({f: cfg["mappings"][f] for f in spec["fields"]})
    if kind == "deduplicate":
        return Deduplicate(spec["key"], spec.get("keep", "last"))
    if kind == "repair_centro_from_mesa":
        return RepairCentroFromMesa()
    if kind == "enrich_from_catalog":
        return EnrichFromCatalog(spec["key"], spec["fields"], db.fetch_lookup(spec["table"], spec["key"], spec["fields"]))
    raise ValueError(f"Transformación desconocida: {kind}")


def build_rule(spec: dict):
    params = {k: v for k, v in spec.items() if k != "rule"}
    if spec["rule"] == "in_catalog":
        params = {"field": spec["field"], "catalog": db.fetch_set(spec["table"], spec["field"])}
    return RULES[spec["rule"]](**params)


def build_pipeline(name: str, fecha: str | None = None, force: bool = False) -> Pipeline:
    cfg = load_config()
    src = source_config(name)
    ext = dict(src["extractor"])
    context: dict = {"fuente": name, "force": force}
    if "path_pattern" in ext:
        if not fecha:
            raise ValueError(f"La fuente '{name}' es incremental y requiere --fecha")
        context["fecha_proceso"] = date.fromisoformat(fecha).isoformat()
        ext["path"] = ext.pop("path_pattern").format(fecha=fecha.replace("-", ""))
    extractor = EXTRACTORS[ext.pop("type")](resolve_path(ext.pop("path")), **ext)
    context.update(archivo=str(extractor.path), hash_archivo=extractor.file_hash() if extractor.path.exists() else None)
    loader_cfg = dict(src["loader"])
    loader = LOADERS[loader_cfg.pop("type")](source=name, **loader_cfg)
    quality = cfg.get("quality", {})
    return Pipeline(
        extractor=extractor,
        transformer=TransformerPipeline(*(build_transformer(t, cfg) for t in src.get("transforms", []))),
        loader=loader,
        validator=Validator([build_rule(r) for r in src.get("rules", [])]),
        name=name,
        context=context,
        on_reject=quality.get("on_reject", "quarantine"),
        max_reject_ratio=quality.get("max_reject_ratio", 1.0),
        key=src["loader"]["natural_key"],
    )
