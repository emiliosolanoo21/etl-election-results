"""Transformaciones reutilizables y puras, compartidas por todas las fuentes."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from typing import Iterable

from src.transformers.base import BaseTransformer
from src.utils.logger import get_logger

logger = get_logger(__name__)

ERRORS = "_errores"


def add_error(record: dict, message: str) -> None:
    record.setdefault(ERRORS, []).append(message)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


class TrimStrings(BaseTransformer):
    """Recorta espacios y convierte cadenas vacías en None."""

    def transform(self, records: Iterable[dict]) -> Iterable[dict]:
        for r in records:
            out = {}
            for k, v in r.items():
                v = v.strip() if isinstance(v, str) else v
                out[k] = None if v == "" else v
            yield out


class NormalizeText(BaseTransformer):
    """Colapsa espacios y aplica Title Case conservando acentos."""

    def __init__(self, fields: list[str]) -> None:
        self.fields = fields

    @staticmethod
    def normalize(value: str | None) -> str | None:
        if value is None:
            return None
        value = re.sub(r"\s+", " ", value.strip())
        return value.title() if value else None

    def transform(self, records: Iterable[dict]) -> Iterable[dict]:
        for r in records:
            yield {**r, **{f: self.normalize(r.get(f)) for f in self.fields if f in r}}


class CanonicalByKey(BaseTransformer):
    """Unifica el nombre por código: prefiere la variante acentuada y luego la más frecuente."""

    def __init__(self, field: str, key: str) -> None:
        self.field = field
        self.key = key

    def transform(self, records: Iterable[dict]) -> Iterable[dict]:
        rows = list(records)
        variants: dict[str, Counter] = defaultdict(Counter)
        for r in rows:
            if r.get(self.field):
                variants[r.get(self.key)][r[self.field]] += 1
        canon = {
            k: max(c, key=lambda v: (v != strip_accents(v), c[v]))
            for k, c in variants.items()
        }
        for r in rows:
            yield {**r, self.field: canon.get(r.get(self.key), r.get(self.field))}


class CastNumeric(BaseTransformer):
    """Convierte texto a int/float manejando miles, coma decimal y vacíos."""

    def __init__(self, fields: dict[str, str]) -> None:
        self.fields = fields

    @staticmethod
    def parse(value, kind: str = "int"):
        if value is None or isinstance(value, (int, float)):
            return value
        s = str(value).strip().replace(" ", "")
        if s == "":
            return None
        if "," in s and "." in s:
            decimal = "," if s.rfind(",") > s.rfind(".") else "."
            s = s.replace("." if decimal == "," else ",", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", s) and kind == "int" else s.replace(",", ".")
        elif kind == "int" and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
            s = s.replace(".", "")
        number = float(s)
        if kind == "int":
            if not number.is_integer():
                raise ValueError(f"'{value}' no es entero")
            return int(number)
        return number

    def transform(self, records: Iterable[dict]) -> Iterable[dict]:
        for r in records:
            r = dict(r)
            for f, kind in self.fields.items():
                try:
                    r[f] = self.parse(r.get(f), kind)
                except ValueError:
                    add_error(r, f"{f}: valor numérico inválido '{r.get(f)}'")
                    r[f] = None
            yield r


class ParseDates(BaseTransformer):
    """Convierte fechas en formatos mixtos a ISO (YYYY-MM-DD)."""

    def __init__(self, fields: list[str], formats: list[str] | None = None) -> None:
        self.fields = fields
        self.formats = formats or ["%Y-%m-%d", "%d/%m/%Y"]

    def parse(self, value):
        if value is None:
            return None
        for fmt in self.formats:
            try:
                return datetime.strptime(str(value).strip(), fmt).date().isoformat()
            except ValueError:
                continue
        raise ValueError(value)

    def transform(self, records: Iterable[dict]) -> Iterable[dict]:
        for r in records:
            r = dict(r)
            for f in self.fields:
                try:
                    r[f] = self.parse(r.get(f))
                except ValueError:
                    add_error(r, f"{f}: fecha no reconocida '{r.get(f)}'")
                    r[f] = None
            yield r


class StandardizeCategories(BaseTransformer):
    """Mapea valores categóricos a su forma canónica; lo no mapeado se conserva."""

    def __init__(self, mapping: dict[str, dict[str, str | None]]) -> None:
        self.mapping = {f: {str(k).lower(): v for k, v in m.items()} for f, m in mapping.items()}

    def transform(self, records: Iterable[dict]) -> Iterable[dict]:
        for r in records:
            r = dict(r)
            for f, m in self.mapping.items():
                v = r.get(f)
                if isinstance(v, str):
                    r[f] = m.get(re.sub(r"\s+", " ", v.strip().lower()), v)
            yield r


class Deduplicate(BaseTransformer):
    """Deja una fila por llave natural; sobrevive la última (corrección más reciente)."""

    def __init__(self, key: list[str], keep: str = "last") -> None:
        self.key = key
        self.keep = keep
        self.stats = {"exactos": 0, "con_diferencias": 0}

    def transform(self, records: Iterable[dict]) -> Iterable[dict]:
        kept: dict[tuple, dict] = {}
        for r in records:
            k = tuple(r.get(c) for c in self.key)
            if k in kept:
                prev = {c: v for c, v in kept[k].items() if c != "_linea"}
                same = prev == {c: v for c, v in r.items() if c != "_linea"}
                self.stats["exactos" if same else "con_diferencias"] += 1
                if self.keep == "first":
                    continue
            kept[k] = r
        if any(self.stats.values()):
            logger.warning("Duplicados por %s: %s", self.key, self.stats)
        yield from kept.values()


class RepairCentroFromMesa(BaseTransformer):
    """Si el centro no coincide con el prefijo de la mesa, la mesa manda."""

    def __init__(self) -> None:
        self.repaired = 0

    def transform(self, records: Iterable[dict]) -> Iterable[dict]:
        for r in records:
            mesa, centro = r.get("codigo_mesa"), r.get("codigo_centro_votacion")
            if mesa and "-" in mesa and centro != mesa.split("-")[0]:
                r = {**r, "codigo_centro_votacion": mesa.split("-")[0], "_centro_original": centro}
                self.repaired += 1
            yield r


class EnrichFromCatalog(BaseTransformer):
    """Completa columnas descriptivas desde un catálogo ya cargado (lookup inyectado)."""

    def __init__(self, key: str, fields: list[str], lookup: dict[str, dict]) -> None:
        self.key = key
        self.fields = fields
        self.lookup = lookup

    def transform(self, records: Iterable[dict]) -> Iterable[dict]:
        for r in records:
            ref = self.lookup.get(r.get(self.key), {})
            yield {**r, **{f: r.get(f) or ref.get(f) for f in self.fields}}
