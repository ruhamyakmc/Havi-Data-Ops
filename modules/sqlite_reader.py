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
        for table in HAVI_TABLES:
            try:
                df = pd.read_sql_query(
                    f'SELECT * FROM "{table}"', conn, dtype=str
                )
                result[table] = df
                logger.debug(f"Read {len(df)} rows from '{table}'.")
            except Exception as exc:
                logger.debug(f"Table '{table}' not found or empty in {db_path}: {exc}")
                result[table] = pd.DataFrame()
    finally:
        conn.close()
    return result
