"""Pruebas de reglas de calidad: sin base de datos."""
from src.quality.validations import (
    Validator, geo_hierarchy, in_catalog, lte, mesa_matches_centro, non_negative, not_null,
)


def test_validator_separa_y_reporta_primera_regla_fallida():
    v = Validator([not_null(["id"]), non_negative(["votos"])])
    res = v.run([{"id": "1", "votos": 3}, {"id": None, "votos": -1}, {"id": "2", "votos": -1}])
    assert len(res.valid) == 1
    assert [rule for _, rule in res.rejected] == ["no_nulo:id", "no_negativo"]


def test_votantes_superan_empadronados():
    _, rule = lte("total_votantes_mesa", "total_empadronados_mesa")
    assert rule({"total_votantes_mesa": 400, "total_empadronados_mesa": 500})
    assert not rule({"total_votantes_mesa": 501, "total_empadronados_mesa": 500})


def test_huerfanos_y_jerarquia():
    assert not in_catalog("c", {"0101001"})[1]({"c": "0104999"})
    assert not geo_hierarchy()[1]({"codigo_departamento": "99", "codigo_municipio": "9999", "codigo_centro_votacion": "0301001"})
    assert mesa_matches_centro()[1]({"codigo_mesa": "0101001-03", "codigo_centro_votacion": "0101001"})
