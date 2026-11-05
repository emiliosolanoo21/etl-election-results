"""Reglas de calidad declarativas: se construyen desde config.yaml por nombre."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable

Rule = tuple[str, Callable[[dict], bool]]


@dataclass
class ValidationResult:
    valid: list[dict] = field(default_factory=list)
    rejected: list[tuple[dict, str]] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        por_regla: dict[str, int] = {}
        for _, rule in self.rejected:
            por_regla[rule] = por_regla.get(rule, 0) + 1
        return {"validos": len(self.valid), "rechazados": len(self.rejected), "por_regla": por_regla}


class Validator:
    """Aplica reglas en orden; un registro se rechaza con la primera que falla."""

    def __init__(self, rules: list[Rule]) -> None:
        self.rules = rules

    def run(self, records: Iterable[dict]) -> ValidationResult:
        result = ValidationResult()
        for r in records:
            for name, rule in self.rules:
                if not rule(r):
                    result.rejected.append((r, name))
                    break
            else:
                result.valid.append(r)
        return result


def not_null(fields: list[str]) -> Rule:
    return f"no_nulo:{','.join(fields)}", lambda r: all(r.get(f) not in (None, "") for f in fields)


def no_parse_errors() -> Rule:
    return "formato_invalido", lambda r: not r.get("_errores")


def non_negative(fields: list[str]) -> Rule:
    return "no_negativo", lambda r: all(r.get(f) is None or r[f] >= 0 for f in fields)


def lte(field: str, max_field: str) -> Rule:
    def check(r: dict) -> bool:
        a, b = r.get(field), r.get(max_field)
        return a is None or b is None or a <= b
    return f"{field}<={max_field}", check


def in_domain(field: str, values: list[str]) -> Rule:
    allowed = set(values)
    return f"dominio:{field}", lambda r: r.get(field) in allowed


def not_in(field: str, values: list[str]) -> Rule:
    banned = set(values)
    return f"valor_centinela:{field}", lambda r: r.get(field) not in banned


def in_catalog(field: str, catalog: set[str]) -> Rule:
    return f"huerfano:{field}", lambda r: r.get(field) in catalog


def date_range(field: str, min: str = "1900-01-01", max: str | None = None) -> Rule:
    upper = max or date.today().isoformat()
    return f"rango_fecha:{field}", lambda r: r.get(field) is None or min <= r[field] <= upper


def geo_hierarchy() -> Rule:
    def check(r: dict) -> bool:
        d, m, c = r.get("codigo_departamento"), r.get("codigo_municipio"), r.get("codigo_centro_votacion")
        return bool(d and m and c) and m.startswith(d) and c.startswith(m)
    return "jerarquia_geografica", check


def mesa_matches_centro() -> Rule:
    def check(r: dict) -> bool:
        mesa, centro = r.get("codigo_mesa") or "", r.get("codigo_centro_votacion") or ""
        return mesa.startswith(centro + "-")
    return "mesa_no_pertenece_al_centro", check


RULES: dict[str, Callable[..., Rule]] = {
    "not_null": not_null,
    "no_parse_errors": no_parse_errors,
    "non_negative": non_negative,
    "lte": lte,
    "in_domain": in_domain,
    "not_in": not_in,
    "in_catalog": in_catalog,
    "date_range": date_range,
    "geo_hierarchy": geo_hierarchy,
    "mesa_matches_centro": mesa_matches_centro,
}
