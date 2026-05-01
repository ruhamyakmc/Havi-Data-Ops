from __future__ import annotations

import os
import sqlite3
import tempfile
import pytest
import pandas as pd
from unittest.mock import patch

from modules.sqlite_reader import read_sqlite_tables, HAVI_TABLES


def _make_sqlite(path: str) -> None:
    """Create a minimal SQLite file with ento_collection and ento_mosquito tables."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE ento_collection (uniqueid TEXT, session_id TEXT, mrccode TEXT)"
    )
    conn.execute(
        "INSERT INTO ento_collection VALUES ('uid1', 'sess1', '12')"
    )
    conn.execute(
        "CREATE TABLE ento_mosquito (uniqueid TEXT, session_id TEXT, mosqnum TEXT)"
    )
    conn.execute(
        "INSERT INTO ento_mosquito VALUES ('uid2', 'sess1', '1')"
    )
    conn.commit()
    conn.close()


def test_reads_present_tables():
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        path = f.name
    try:
        _make_sqlite(path)
        tables = read_sqlite_tables(path)
        assert 'ento_collection' in tables
        assert len(tables['ento_collection']) == 1
        assert tables['ento_collection'].iloc[0]['uniqueid'] == 'uid1'
        assert 'ento_mosquito' in tables
        assert len(tables['ento_mosquito']) == 1
    finally:
        os.unlink(path)


def test_missing_table_returns_empty_dataframe():
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        path = f.name
    try:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE ento_collection (uniqueid TEXT)")
        conn.commit()
        conn.close()
        tables = read_sqlite_tables(path)
        # larvae not in this db — should return empty DataFrame, not raise
        assert isinstance(tables['larvae'], pd.DataFrame)
        assert tables['larvae'].empty
    finally:
        os.unlink(path)


def test_all_havi_tables_keys_present():
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        path = f.name
    try:
        conn = sqlite3.connect(path)
        conn.commit()
        conn.close()
        tables = read_sqlite_tables(path)
        for t in HAVI_TABLES:
            assert t in tables, f"Missing key: {t}"
    finally:
        os.unlink(path)


def test_all_columns_read_as_str():
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        path = f.name
    try:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE ento_collection (uniqueid TEXT, mrccode INTEGER)")
        conn.execute("INSERT INTO ento_collection VALUES ('uid1', 12)")
        conn.commit()
        conn.close()
        tables = read_sqlite_tables(path)
        assert tables['ento_collection']['mrccode'].dtype == object
    finally:
        os.unlink(path)


def test_existing_table_read_error_raises():
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        path = f.name
    try:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE ento_collection (uniqueid TEXT)")
        conn.commit()
        conn.close()

        with patch('modules.sqlite_reader.pd.read_sql_query', side_effect=Exception('boom')):
            with pytest.raises(RuntimeError, match="Failed to read table 'ento_collection'"):
                read_sqlite_tables(path)
    finally:
        os.unlink(path)
