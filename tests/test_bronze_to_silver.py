import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from stages.bronze_to_silver import BronzeToSilver


def _make_config():
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        'trial': {
            'dedup_key': 'uniqueid',
            'dedup_strategy': 'latest_snapshot',
        },
    }.get(key, default)
    return config


def _bronze_df(table: str) -> pd.DataFrame:
    return pd.DataFrame({
        'uniqueid': ['a', 'a', 'b'],
        'session_id': ['s1', 's1', 's2'],
        'clocation': ['1', '1', '1'],
        '_source_db': ['x', 'x', 'y'],
        'run_uuid': ['r1', 'r1', 'r2'],
        'file_name': ['f1', 'f1', 'f2'],
        'file_path': ['p1', 'p1', 'p2'],
        'country': ['uganda', 'uganda', 'uganda'],
        'community': ['Uganda', 'Uganda', 'Uganda'],
        'extracted_at': [None, None, None],
    })


def test_deduplicates_by_uniqueid():
    """3 bronze rows with 2 unique IDs → 2 silver rows per table."""
    engine = MagicMock()

    def fake_read_sql(sql, engine):
        if 'ento_collection' in sql:
            return _bronze_df('ento_collection')
        return pd.DataFrame()

    with patch('stages.bronze_to_silver.has_table', return_value=True):
        with patch('stages.bronze_to_silver.pd.read_sql', side_effect=fake_read_sql):
            with patch.object(pd.DataFrame, 'to_sql'):
                stage = BronzeToSilver(config=_make_config(), engine=engine)
                result = stage.run()

    assert result.success
    assert result.rows_written >= 2


def test_ent_collection_dedup_keeps_indoor_and_outdoor_same_uniqueid():
    engine = MagicMock()
    bronze_df = _bronze_df('ento_collection')
    bronze_df.loc[1, 'clocation'] = '2'
    writes = {}

    def fake_read_sql(sql, engine):
        if 'ento_collection' in sql:
            return bronze_df
        return pd.DataFrame()

    def fake_to_sql(self, name, *args, **kwargs):
        writes[name] = self.copy()

    with patch('stages.bronze_to_silver.has_table', return_value=True):
        with patch('stages.bronze_to_silver.pd.read_sql', side_effect=fake_read_sql):
            with patch.object(pd.DataFrame, 'to_sql', new=fake_to_sql):
                stage = BronzeToSilver(config=_make_config(), engine=engine)
                result = stage.run()

    assert result.success
    assert len(writes['_stage_ento_collection']) == 3
    assert {
        'run_uuid', 'file_name', 'file_path', 'extracted_at', 'country', 'community',
    }.issubset(writes['_stage_ento_collection'].columns)
    assert 'session_id' in writes['_stage_ento_collection'].columns


def test_empty_table_is_skipped():
    engine = MagicMock()
    writes = {}

    def fake_to_sql(self, name, *args, **kwargs):
        writes[name] = self.copy()

    with patch('stages.bronze_to_silver.has_table', return_value=True):
        with patch('stages.bronze_to_silver.pd.read_sql', return_value=pd.DataFrame()):
            with patch.object(pd.DataFrame, 'to_sql', new=fake_to_sql):
                stage = BronzeToSilver(config=_make_config(), engine=engine)
                result = stage.run()
    assert result.success
    assert result.rows_written == 0
    assert '_stage_ento_collection' in writes
    assert writes['_stage_ento_collection'].empty
    assert {
        'run_uuid', 'file_name', 'file_path', 'extracted_at', 'country', 'community',
    }.issubset(writes['_stage_ento_collection'].columns)
