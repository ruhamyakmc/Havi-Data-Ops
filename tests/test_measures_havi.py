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


def test_orphan_hbo_person_detected_despite_per_site_scoping():
    """Regression: hbo_person has no mrccode of its own, so the per-site loop
    scopes person records by matching them against that site's household
    session_ids — which silently discards true orphans before validate_hbo_person
    ever sees them. orphan_hbo_person must still be caught via the global pass.
    """
    engine = MagicMock()

    household_df = pd.DataFrame({
        'uniqueid': ['huid1'],
        'session_id': ['312010595-2026-04-20'],
        'mrccode': ['12'],
        'hhid': ['312010595'],
        'dateofobservation': ['2026-04-20'],
        'numpeople': ['1'],
    })
    person_df = pd.DataFrame({
        'uniqueid': ['puid1', 'puid2'],
        'session_id': ['312010595-2026-04-20', 'orphan-session-2026-05-28'],
        'individualnum': ['1', '1'],
    })

    read_map = {
        'ento_collection': pd.DataFrame(),
        'ento_mosquito': pd.DataFrame(),
        'pheno_site': pd.DataFrame(),
        'pheno_assay': pd.DataFrame(),
        'hbo_household': household_df,
        'hbo_person': person_df,
    }

    def fake_read_sql(sql, eng):
        for key, val in read_map.items():
            if f'"{key}"' in sql:
                return val
        return pd.DataFrame()

    captured: dict[str, pd.DataFrame] = {}

    def fake_to_sql(self, name, conn, **kwargs):
        captured['report'] = self.copy()

    with patch('stages.measures_havi.has_table', return_value=True):
        with patch('stages.measures_havi.pd.read_sql', side_effect=fake_read_sql):
            with patch('stages.measures_havi._load_sql_files', return_value=[]):
                with patch.object(pd.DataFrame, 'to_sql', new=fake_to_sql):
                    stage = MeasuresHavi(config=_make_config(), engine=engine)
                    result = stage.run()

    assert result.success
    report = captured['report']
    orphan_rows = report[report['check'] == 'orphan_hbo_person']
    assert len(orphan_rows) == 1
    assert orphan_rows.iloc[0]['session_id'] == 'orphan-session-2026-05-28'
