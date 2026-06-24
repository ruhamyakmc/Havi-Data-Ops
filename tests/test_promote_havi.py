import pytest
from unittest.mock import MagicMock

from stages.promote_havi import PromoteHavi


def test_promote_copies_all_gold_tables():
    engine = MagicMock()
    mock_conn = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    mock_conn.execute.return_value.fetchall.return_value = [
        ('d_participant',), ('d_enrollment',),
    ]
    mock_conn.execute.return_value.scalar.return_value = True

    config = MagicMock()
    stage = PromoteHavi(config=config, engine=engine)
    result = stage.run()

    assert result.success
    assert result.rows_written == 2

    executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]

    assert any('TRUNCATE TABLE havi."d_participant"' in s for s in executed_sql)
    assert any('INSERT INTO havi."d_participant"' in s for s in executed_sql)
    assert any('TRUNCATE TABLE havi."d_enrollment"' in s for s in executed_sql)
    assert any('INSERT INTO havi."d_enrollment"' in s for s in executed_sql)
    assert not any('CASCADE' in s for s in executed_sql)
    assert not any('"_new_' in s for s in executed_sql)


def test_promote_rejects_invalid_table_name():
    """Table names containing characters outside [a-z0-9_] must raise ValueError."""
    engine = MagicMock()
    mock_conn = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    mock_conn.execute.return_value.fetchall.return_value = [
        ('d_participant; DROP TABLE havi.ento_collection--',)
    ]

    stage = PromoteHavi(config=MagicMock(), engine=engine)
    with pytest.raises(ValueError, match="Invalid table name"):
        stage.run()
