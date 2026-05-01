from __future__ import annotations

import sqlite3
import logging

import pandas as pd

logger = logging.getLogger(__name__)

HAVI_TABLES = [
    'ento_collection',
    'ento_mosquito',
    'pheno_site',
    'pheno_assay',
    'hbo_household',
    'hbo_person',
    'larvae',
]


def read_sqlite_tables(db_path: str) -> dict[str, pd.DataFrame]:
    """
    Open *db_path* and read all HAVI_TABLES into DataFrames.
    All columns are read as str (dtype=object) so the bronze layer
    stores raw text — type coercions happen in silver.
    Tables absent from the SQLite are returned as empty DataFrames.
    """
    result: dict[str, pd.DataFrame] = {}
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        existing_tables = {row[0] for row in rows}
        for table in HAVI_TABLES:
            if table not in existing_tables:
                logger.debug(f"Table '{table}' not found in {db_path}.")
                result[table] = pd.DataFrame()
                continue
            try:
                df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn, dtype=str)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to read table '{table}' from {db_path}: {exc}"
                ) from exc
            result[table] = df
            logger.debug(f"Read {len(df)} rows from '{table}'.")
    finally:
        conn.close()
    return result
