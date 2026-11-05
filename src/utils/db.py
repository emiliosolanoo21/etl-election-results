"""Acceso a PostgreSQL con psycopg2: transacciones explícitas y carga masiva."""
from __future__ import annotations

from contextlib import contextmanager

import psycopg2
from psycopg2.extras import execute_values

from src.config.settings import DBSettings


def connect():
    s = DBSettings.from_env()
    return psycopg2.connect(host=s.host, port=s.port, dbname=s.database, user=s.user, password=s.password)


@contextmanager
def get_connection():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_many(conn, table: str, columns: list[str], rows: list[tuple]) -> int:
    if not rows:
        return 0
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s"
    with conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=1000)
    return len(rows)


def fetch_set(table: str, column: str) -> set[str]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL")
        return {row[0] for row in cur.fetchall()}


def fetch_lookup(table: str, key: str, fields: list[str]) -> dict[str, dict]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {key}, {', '.join(fields)} FROM {table}")
        return {row[0]: dict(zip(fields, row[1:])) for row in cur.fetchall()}
