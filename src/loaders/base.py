"""Contrato de carga: el loader abre la transacción y delega en load_with."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from src.utils.db import get_connection


class BaseLoader(ABC):
    def __init__(self, table: str, natural_key: list[str], columns: list[str] | None = None) -> None:
        self.table = table
        self.natural_key = natural_key
        self.columns = columns or []
        self.stats: dict = {}

    def load(self, records: Iterable[dict], context: dict | None = None) -> int:
        """Carga todo en una única transacción: o queda completo o no queda nada."""
        with get_connection() as conn:
            return self.load_with(conn, list(records), context or {})

    @abstractmethod
    def load_with(self, conn, records: list[dict], context: dict) -> int:
        raise NotImplementedError
