import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from stages.measures_havi import MeasuresHavi


def _make_config():
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        'trial': {'name': 'havi'},
    }.get(key, default)
    return config


def _ento_collection() -> pd.DataFrame:
    return pd.DataFrame({
        'uniqueid': ['uid1'],
        'session_id': ['sess1'],
        'mrccode': ['12'],
        'hhid': ['312010595'],
        'dateofcollection': ['2026-04-20'],
        'starttime': ['2026-04-20T20:00:00'],
        'stoptime': ['2026-04-20T22:00:00'],
        'datasource': ['1'],
        'clocation': ['1'],
        'numfanoph': ['0'],
        'nummanoph': ['0'],
        'numculex': ['0'],
    })


def test_measures_havi_runs_successfully():
    engine = MagicMock()

    read_map = {
        'silver_havi.ento_collection': _ento_collection(),
        'silver_havi.ento_mosquito': pd.DataFrame(),
        'silver_havi.pheno_site': pd.DataFrame(),
        'silver_havi.pheno_assay': pd.DataFrame(),
    }

    def fake_read_sql(sql, eng):
        for key, val in read_map.items():
            if key in sql:
                return val
        return pd.DataFrame()

    with patch('stages.measures_havi.has_table', return_value=True):
        with patch('stages.measures_havi.pd.read_sql', side_effect=fake_read_sql):
            with patch('stages.measures_havi._load_sql_files', return_value=[]):
                with patch.object(pd.DataFrame, 'to_sql'):
                    stage = MeasuresHavi(config=_make_config(), engine=engine)
                    result = stage.run()

    assert result.success


def test_measures_havi_empty_collection_skips():
    engine = MagicMock()
    with patch('stages.measures_havi.has_table', return_value=True):
        with patch('stages.measures_havi.pd.read_sql', return_value=pd.DataFrame()):
            with patch('stages.measures_havi._load_sql_files', return_value=[]):
                stage = MeasuresHavi(config=_make_config(), engine=engine)
                result = stage.run()
    assert result.success
    assert result.rows_written == 0
