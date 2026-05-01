import pytest
from unittest.mock import MagicMock, patch, call
from modules.db import create_db_engine, init_schemas, log_pipeline_row_counts, SCHEMAS

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
        return result

    mock_conn.execute.side_effect = execute_side_effect

    with caplog.at_level('WARNING'):
        log_pipeline_row_counts(mock_engine, 'run-1', tables=['ento_collection'])

    assert 'Layer row-count mismatch for ento_collection' in caplog.text
