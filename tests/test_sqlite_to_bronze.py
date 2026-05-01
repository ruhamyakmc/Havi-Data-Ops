from __future__ import annotations

import os
import sqlite3
import tempfile
import zipfile
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch, call

from stages.sqlite_to_bronze import SqliteToBronze


def _make_engine():
    """Create a mock engine whose begin() context manager yields a mock connection."""
    engine = MagicMock()
    mock_conn = MagicMock()
    # engine.begin() used as context manager: with engine.begin() as conn:
    engine.begin.return_value.__enter__.return_value = mock_conn
    engine.begin.return_value.__exit__.return_value = False
    # engine.connect() used as context manager for the meta-skip check
    mock_connect_conn = MagicMock()
    mock_connect_conn.execute.return_value.fetchone.return_value = None  # not already loaded
    engine.connect.return_value.__enter__.return_value = mock_connect_conn
    engine.connect.return_value.__exit__.return_value = False
    return engine, mock_conn


def _make_config():
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        'communities': {
            'uganda': {
                'community_name': 'Uganda',
                'country': 'uganda',
                'remotefilepath_download': '/data/',
            }
        },
        'trial': {'dedup_key': 'uniqueid'},
        'excluded_tablets': [],
    }.get(key, default)
    return config


def _make_sqlite_zip(directory: str) -> str:
    """Create a minimal zip containing a SQLite with ento_collection data."""
    db_path = os.path.join(directory, 'havi_entomology.sqlite')
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE ento_collection "
        "(uniqueid TEXT, session_id TEXT, mrccode TEXT, starttime TEXT, stoptime TEXT)"
    )
    conn.execute("INSERT INTO ento_collection VALUES ('uid1','s1','12','2026-04-29','2026-04-29')")
    conn.commit()
    conn.close()

    zip_path = os.path.join(directory, 'havi_entomology_109_2026-04-29_11_00.zip')
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(db_path, 'havi_entomology.sqlite')
    return zip_path


def _make_sqlite_zip_with_drift(directory: str) -> str:
    db_path = os.path.join(directory, 'havi_entomology.sqlite')
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE ento_collection "
        "(uniqueid TEXT, session_id TEXT, mrccode TEXT, unexpected_col TEXT)"
    )
    conn.execute("INSERT INTO ento_collection VALUES ('uid1','s1','12','new')")
    conn.commit()
    conn.close()

    zip_path = os.path.join(directory, 'havi_entomology_109_2026-04-29_11_00.zip')
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(db_path, 'havi_entomology.sqlite')
    return zip_path


def test_stage_ingests_ento_collection():
    """Stage reads a zip, finds ento_collection data, and writes to bronze_havi."""
    with tempfile.TemporaryDirectory() as tmp:
        extract_dir = os.path.join(tmp, 'Uganda')
        os.makedirs(extract_dir)
        _make_sqlite_zip(extract_dir)

        engine, mock_conn = _make_engine()
        written_tables: list[tuple] = []

        original_to_sql = pd.DataFrame.to_sql

        def capture_to_sql(self, name, conn, schema=None, if_exists=None, index=None):
            written_tables.append((schema, name))

        with patch('stages.sqlite_to_bronze.get_country_paths',
                   return_value={'extract_path': extract_dir}):
            with patch.object(pd.DataFrame, 'to_sql', capture_to_sql):
                stage = SqliteToBronze(config=_make_config(), engine=engine)
                result = stage.run()

        assert result.success
        assert result.rows_written == 1  # 1 row in ento_collection
        # Both the data table and meta table should have been written
        schemas_and_tables = [(s, t) for s, t in written_tables]
        assert ('bronze_havi', 'ento_collection') in schemas_and_tables
        assert ('bronze_havi', 'meta') in schemas_and_tables


def test_stage_succeeds_with_no_sqlite_files():
    """Stage returns success with 0 rows when extract dir has no zip files."""
    with tempfile.TemporaryDirectory() as tmp:
        extract_dir = os.path.join(tmp, 'Uganda')
        os.makedirs(extract_dir)

        engine, _ = _make_engine()
        with patch('stages.sqlite_to_bronze.get_country_paths',
                   return_value={'extract_path': extract_dir}):
            stage = SqliteToBronze(config=_make_config(), engine=engine)
            result = stage.run()

        assert result.success
        assert result.rows_written == 0


def test_stage_warns_on_schema_drift():
    with tempfile.TemporaryDirectory() as tmp:
        extract_dir = os.path.join(tmp, 'Uganda')
        os.makedirs(extract_dir)
        _make_sqlite_zip_with_drift(extract_dir)

        engine, _ = _make_engine()

        with patch('stages.sqlite_to_bronze.get_country_paths',
                   return_value={'extract_path': extract_dir}):
            with patch.object(pd.DataFrame, 'to_sql', lambda *args, **kwargs: None):
                stage = SqliteToBronze(config=_make_config(), engine=engine)
                result = stage.run()

        assert result.success
        assert any(w['check'] == 'schema_drift' for w in result.warnings)
        drift = next(w for w in result.warnings if w['check'] == 'schema_drift')
        assert 'unexpected_col' in drift['detail']
