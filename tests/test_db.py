import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call
from modules.db import (
    create_db_engine,
    create_table_indexes,
    init_schemas,
    log_pipeline_run,
    log_pipeline_row_counts,
    replace_table_from_select,
    SCHEMAS,
)
from modules.havi_schema import ensure_empty_table
from stages.base import StageResult

def test_init_schemas_creates_all_schemas():
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    init_schemas(mock_engine)

    executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    for schema in SCHEMAS:
        assert any(schema in sql for sql in executed_sql), f"Schema {schema} not created"
    mock_conn.commit.assert_called_once()

def test_schemas_list_contains_all_layers():
    assert set(SCHEMAS) == {'bronze_havi', 'silver_havi', 'gold_havi', 'havi'}


def test_ensure_empty_table_adds_missing_columns_to_existing_table():
    mock_conn = MagicMock()

    ensure_empty_table(mock_conn, 'bronze_havi', 'ento_mosquito', ['uniqueid', 'clocation'])

    executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    assert any('CREATE TABLE IF NOT EXISTS "bronze_havi"."ento_mosquito"' in sql
               for sql in executed_sql)
    assert any('ADD COLUMN IF NOT EXISTS "uniqueid" TEXT' in sql for sql in executed_sql)
    assert any('ADD COLUMN IF NOT EXISTS "clocation" TEXT' in sql for sql in executed_sql)

def test_create_db_engine_reads_secret_file(tmp_path):
    secret_file = tmp_path / 'db_password'
    secret_file.write_text('secret')
    config = MagicMock()
    config.get.return_value = {
        'host': 'localhost', 'port': 5432, 'name': 'havi',
        'user': 'havi_user', 'password_secret_file': str(secret_file)
    }
    with patch('modules.db.create_engine') as mock_create:
        create_db_engine(config)
        url = mock_create.call_args[0][0]
        assert url.password == 'secret'
        assert url.host == 'localhost'
        assert mock_create.call_args[1].get('pool_pre_ping') is True

def test_create_db_engine_sets_statement_timeout(tmp_path):
    secret_file = tmp_path / 'db_password'
    secret_file.write_text('secret')
    config = MagicMock()
    config.get.return_value = {
        'host': 'localhost', 'port': 5432, 'name': 'havi',
        'user': 'havi_user', 'password_secret_file': str(secret_file)
    }
    with patch('modules.db.create_engine') as mock_create:
        create_db_engine(config)
        connect_args = mock_create.call_args[1].get('connect_args', {})
        options = connect_args.get('options', '')
        assert 'statement_timeout' in options
        assert 'lock_timeout' in options


def test_log_pipeline_row_counts_writes_counts():
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    def execute_side_effect(sql, params=None):
        sql_text = str(sql)
        result = MagicMock()
        if 'SELECT EXISTS' in sql_text:
            result.scalar.return_value = params['table'] == 'ento_collection'
        elif 'SELECT COUNT(*)' in sql_text:
            result.scalar_one.return_value = 7
        elif 'SELECT row_count' in sql_text:
            result.scalar.return_value = None
        return result

    mock_conn.execute.side_effect = execute_side_effect

    log_pipeline_row_counts(mock_engine, 'run-1', tables=['ento_collection'])

    executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    assert any('CREATE TABLE IF NOT EXISTS havi.pipeline_row_counts' in sql for sql in executed_sql)
    assert any('INSERT INTO havi.pipeline_row_counts' in sql for sql in executed_sql)


def test_log_pipeline_row_counts_warns_on_mismatch(caplog):
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    counts = {
        'bronze_havi': 10,
        'silver_havi': 7,
        'gold_havi': 7,
        'havi': 6,
    }

    def execute_side_effect(sql, params=None):
        sql_text = str(sql)
        result = MagicMock()
        if 'SELECT EXISTS' in sql_text:
            result.scalar.return_value = True
        elif 'SELECT COUNT(*)' in sql_text:
            schema = next(s for s in counts if f'"{s}"."ento_collection"' in sql_text)
            result.scalar_one.return_value = counts[schema]
        elif 'SELECT row_count' in sql_text:
            result.scalar.return_value = None
        return result

    mock_conn.execute.side_effect = execute_side_effect

    with caplog.at_level('WARNING'):
        log_pipeline_row_counts(mock_engine, 'run-1', tables=['ento_collection'])

    assert 'Layer row-count mismatch for ento_collection' in caplog.text


def test_log_pipeline_row_counts_warns_on_large_drop(caplog):
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    def execute_side_effect(sql, params=None):
        sql_text = str(sql)
        result = MagicMock()
        if 'SELECT EXISTS' in sql_text:
            result.scalar.return_value = params['table'] == 'ento_collection'
        elif 'SELECT COUNT(*)' in sql_text:
            result.scalar_one.return_value = 60
        elif 'SELECT row_count' in sql_text:
            result.scalar.return_value = 100
        return result

    mock_conn.execute.side_effect = execute_side_effect

    with caplog.at_level('WARNING'):
        log_pipeline_row_counts(mock_engine, 'run-2', tables=['ento_collection'])

    assert 'Row-count drop alert for' in caplog.text
    assert 'current=60 previous=100' in caplog.text


def test_log_pipeline_run_writes_stage_duration():
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    result = StageResult(success=True, rows_written=3, metadata={'duration_s': 1.25})

    log_pipeline_run(
        mock_engine,
        'run-1',
        datetime.now(timezone.utc),
        {'sqlite_to_bronze': result},
        ['sqlite_to_bronze'],
    )

    executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    assert any('ADD COLUMN IF NOT EXISTS duration_s' in sql for sql in executed_sql)
    insert_call = next(
        c for c in mock_conn.execute.call_args_list
        if 'INSERT INTO havi.pipeline_run_log' in str(c.args[0])
    )
    assert insert_call.args[1][0]['duration_s'] == 1.25


def test_create_table_indexes_creates_configured_indexes():
    mock_conn = MagicMock()

    create_table_indexes(mock_conn, 'silver_havi', 'ento_collection')

    executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    assert any('CREATE UNIQUE INDEX IF NOT EXISTS "uidx_ento_collection_uniqueid_clocation"'
               in sql for sql in executed_sql)
    assert any('WHERE "uniqueid" IS NOT NULL AND "clocation" IS NOT NULL' in sql
               for sql in executed_sql)
    assert not any('CREATE INDEX IF NOT EXISTS "idx_ento_collection_uniqueid_clocation"' in sql
               for sql in executed_sql)
    assert any('ON "silver_havi"."ento_collection" ("uniqueid", "clocation")' in sql
               for sql in executed_sql)
    assert any('"idx_ento_collection_run_uuid"' in sql for sql in executed_sql)


def test_create_table_indexes_uses_default_uniqueid_key():
    mock_conn = MagicMock()

    create_table_indexes(mock_conn, 'gold_havi', 'ento_mosquito')

    executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    assert any('CREATE UNIQUE INDEX IF NOT EXISTS "uidx_ento_mosquito_uniqueid"' in sql
               for sql in executed_sql)
    assert any('WHERE "uniqueid" IS NOT NULL' in sql for sql in executed_sql)


def test_create_table_indexes_ignores_unmodeled_tables():
    mock_conn = MagicMock()

    create_table_indexes(mock_conn, 'havi', 'ds_validation_report')

    mock_conn.execute.assert_not_called()


def test_replace_table_from_select_uses_explicit_column_definitions():
    mock_conn = MagicMock()

    replace_table_from_select(
        mock_conn,
        'gold_havi',
        'ento_collection',
        ['uniqueid', 'extracted_at'],
        'SELECT uniqueid, extracted_at FROM silver_havi.ento_collection',
    )

    executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    assert any(
        'CREATE TABLE "gold_havi"."_stage_ento_collection" '
        '("uniqueid" TEXT, "extracted_at" TIMESTAMPTZ)' in sql
        for sql in executed_sql
    )
    assert any(
        'INSERT INTO "gold_havi"."_stage_ento_collection" '
        '("uniqueid", "extracted_at") SELECT src."uniqueid", src."extracted_at" '
        'FROM (SELECT uniqueid, extracted_at FROM silver_havi.ento_collection) AS src'
        in sql
        for sql in executed_sql
    )
    assert any('DROP TABLE IF EXISTS "gold_havi"."ento_collection"' in sql
               for sql in executed_sql)
