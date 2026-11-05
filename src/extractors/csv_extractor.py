"""Extractor de archivos CSV en streaming."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Iterable

from src.extractors.base import BaseExtractor
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CSVExtractor(BaseExtractor):
    def __init__(self, path: str | Path, encoding: str = "utf-8-sig", **options) -> None:
        super().__init__(path=str(path), encoding=encoding, **options)
        self.path = Path(path)
        self.encoding = encoding
        self.rows_read = 0

    def extract(self) -> Iterable[dict]:
        if not self.path.exists():
            raise FileNotFoundError(f"No existe el archivo de origen: {self.path}")
        logger.info("Leyendo %s", self.path)
        with open(self.path, newline="", encoding=self.encoding) as fh:
            reader = csv.DictReader(fh)
            reader.fieldnames = [c.strip().lower() for c in reader.fieldnames or []]
            for line_no, row in enumerate(reader, start=2):
                self.rows_read += 1
                yield {**row, "_linea": line_no}

    def file_hash(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def metadata(self) -> dict:
        return {"extractor": type(self).__name__, "archivo": str(self.path), "leidos": self.rows_read}
