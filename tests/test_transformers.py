"""Pruebas unitarias de transformaciones: sin base de datos."""
import pytest

from src.transformers.base import TransformerPipeline
from src.transformers.common import (
    CanonicalByKey,
    CastNumeric,
    Deduplicate,
    NormalizeText,
    ParseDates,
    RepairCentroFromMesa,
    StandardizeCategories,
    TrimStrings,
)


def run(transformer, records):
    return list(transformer.transform(records))


def test_trim_strings_vacio_a_none():
    out = run(TrimStrings(), [{"nombre": "  Sololá  ", "zona": "   "}])
    assert out[0] == {"nombre": "Sololá", "zona": None}


@pytest.mark.parametrize("raw", [" Guatemala ", "GUATEMALA", "guatemala", "Guatemala"])
def test_normalize_text_variantes_de_mayusculas_y_espacios(raw):
    assert run(NormalizeText(["n"]), [{"n": raw}])[0]["n"] == "Guatemala"


def test_normalize_text_colapsa_espacios_internos_y_respeta_none():
    out = run(NormalizeText(["n", "m"]), [{"n": "Instituto  No. 2,  MIXCO", "m": None}])
    assert out[0] == {"n": "Instituto No. 2, Mixco", "m": None}


def test_canonical_by_key_prefiere_variante_acentuada():
    records = [{"c": "17", "n": "Peten"}, {"c": "17", "n": "Peten"}, {"c": "17", "n": "Petén"}]
    assert {r["n"] for r in run(CanonicalByKey("n", "c"), records)} == {"Petén"}


@pytest.mark.parametrize(
    "raw,kind,expected",
    [("1,234", "int", 1234), ("1.234", "int", 1234), ("16,489162", "float", 16.489162),
     ("-91.64", "float", -91.64), ("1.234,5", "float", 1234.5), ("", "int", None), ("-12", "int", -12)],
)
def test_cast_numeric_formatos(raw, kind, expected):
    assert CastNumeric.parse(raw, kind) == expected


def test_cast_numeric_invalido_marca_error_sin_romper():
    out = run(CastNumeric({"v": "int"}), [{"v": "abc"}])
    assert out[0]["v"] is None and out[0]["_errores"]


def test_parse_dates_formato_mixto():
    out = run(ParseDates(["f"]), [{"f": "05/03/2019"}, {"f": "2019-03-05"}, {"f": None}])
    assert [r["f"] for r in out] == ["2019-03-05", "2019-03-05", None]


def test_parse_dates_invalida_queda_marcada():
    out = run(ParseDates(["f"]), [{"f": "31/02/2020"}])
    assert out[0]["f"] is None and "fecha no reconocida" in out[0]["_errores"][0]


def test_standardize_categories_y_no_mapeados():
    mapping = {"sexo": {"m": "M", "masculino": "M"}, "zona": {"sin zona": None}}
    out = run(StandardizeCategories(mapping), [{"sexo": "MASCULINO", "zona": "SIN ZONA"}, {"sexo": "x", "zona": "5"}])
    assert out[0] == {"sexo": "M", "zona": None}
    assert out[1] == {"sexo": "x", "zona": "5"}


def test_deduplicate_exactos_y_con_diferencias_sobrevive_ultimo():
    t = Deduplicate(["id"])
    records = [{"id": 1, "v": "a", "_linea": 2}, {"id": 1, "v": "a", "_linea": 3}, {"id": 1, "v": "b", "_linea": 4}]
    out = run(t, records)
    assert out == [{"id": 1, "v": "b", "_linea": 4}]
    assert t.stats == {"exactos": 1, "con_diferencias": 1}


def test_deduplicate_entrada_vacia():
    assert run(Deduplicate(["id"]), []) == []


def test_repair_centro_from_mesa():
    out = run(RepairCentroFromMesa(), [{"codigo_centro_votacion": "0104999", "codigo_mesa": "0502002-09"}])
    assert out[0]["codigo_centro_votacion"] == "0502002"


def test_pipeline_compuesto():
    pipe = TransformerPipeline(TrimStrings(), CastNumeric({"v": "int"}))
    assert run(pipe, [{"v": " 1,500 "}]) == [{"v": 1500}]
