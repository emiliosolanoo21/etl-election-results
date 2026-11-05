"""Configuración: estructura en YAML, credenciales solo en variables de entorno."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).with_name("config.yaml")


@dataclass(frozen=True)
class DBSettings:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "DBSettings":
        return cls(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "electoral_db"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
        )


@lru_cache(maxsize=None)
def load_config(path: str | None = None) -> dict:
    with open(path or CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def source_config(name: str) -> dict:
    try:
        return load_config()["sources"][name]
    except KeyError as exc:
        raise KeyError(f"Fuente '{name}' no está definida en config.yaml") from exc


def resolve_path(relative: str) -> Path:
    """Resuelve rutas del YAML respecto a la raíz del proyecto."""
    return PROJECT_ROOT / relative
