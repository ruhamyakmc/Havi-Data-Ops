from pathlib import Path
from unittest.mock import MagicMock

from modules.migrations import _load_migration_files, run_migrations


def test_load_migration_files_returns_sorted_sql_paths(tmp_path):
    (tmp_path / '002_second.sql').write_text('SELECT 2')
    (tmp_path / '001_first.sql').write_text('SELECT 1')
    (tmp_path / 'notes.txt').write_text('ignore me')

    files = _load_migration_files(tmp_path)

    assert [f.name for f in files] == ['001_first.sql', '002_second.sql']


def test_run_migrations_applies_unseen_files(tmp_path):
    migration = tmp_path / '001_test.sql'
    migration.write_text('CREATE TABLE havi.example (id TEXT)')
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    mock_conn.execute.return_value.fetchall.return_value = []

    run_migrations(mock_engine, tmp_path)

    executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    assert any('CREATE TABLE IF NOT EXISTS havi.schema_migrations' in sql
               for sql in executed_sql)
    assert any('CREATE TABLE havi.example' in sql for sql in executed_sql)
    assert any('INSERT INTO havi.schema_migrations' in sql for sql in executed_sql)


def test_run_migrations_skips_applied_files(tmp_path):
    migration = tmp_path / '001_test.sql'
    migration.write_text('CREATE TABLE havi.example (id TEXT)')
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    mock_conn.execute.return_value.fetchall.return_value = [('001_test.sql',)]

    run_migrations(mock_engine, tmp_path)

    executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    assert not any('CREATE TABLE havi.example' in sql for sql in executed_sql)
