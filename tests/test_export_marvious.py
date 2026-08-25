from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch

import pandas as pd

from stages.export_marvious import ExportMarvious, zero_fill_mosquito


def _make_stage(mrccodes=None, n=2):
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        'marvious': {
            'n_collections': n,
            'mrccodes': mrccodes or ['64', '66', '70'],
        },
    }.get(key, default)
    engine = MagicMock()
    return ExportMarvious(config=config, engine=engine)


def _make_collection(mrccodes):
    rows = []
    for m in mrccodes:
        for night, ds, cl in [('2026-05-01', '1', '1'), ('2026-05-02', '1', '2')]:
            rows.append({
                'hhid': f'{m}HH1',
                'mrccode': m,
                'dateofcollection': night,
                'session_id': f'{m}HH1-{night}-{cl}',
                'datasource': ds,
                'clocation': cl,
                'aspirations_method': '-6',
            })
    return pd.DataFrame(rows)


def test_marvious_exports_only_configured_mrccodes():
    """ExportMarvious only includes rows for its configured MRC codes."""
    stage = _make_stage(mrccodes=['64', '66'])
    coll = _make_collection(['64', '66', '70'])
    empty = pd.DataFrame(columns=['session_id', 'mrccode', 'hhid'])
    hbo_empty = pd.DataFrame(columns=['hhid', 'mrccode', 'session_id', 'dateofobservation'])

    with patch.object(stage, '_read_silver', side_effect=[coll, empty, hbo_empty, empty]):
        with patch('stages.export_visits.Path.mkdir'):
            with patch('stages.export_visits.Path.write_bytes') as mock_write:
                result = stage.run()

    assert result.success
    zf_bytes = mock_write.call_args[0][0]
    with zipfile.ZipFile(io.BytesIO(zf_bytes)) as zf:
        hlc_csv = zf.read('hlc_collection.csv').decode()
    mrcs = {r.split(',')[1] for r in hlc_csv.strip().splitlines()[1:] if r}
    assert mrcs == {'64', '66'}
    assert '70' not in mrcs


def test_marvious_zip_name_contains_marvious():
    """Output zip filename includes 'marvious'."""
    stage = _make_stage()
    coll = _make_collection(['64'])
    empty = pd.DataFrame(columns=['session_id', 'mrccode', 'hhid'])
    hbo_empty = pd.DataFrame(columns=['hhid', 'mrccode', 'session_id', 'dateofobservation'])

    written_path = []

    def capture_write(data):
        pass

    with patch.object(stage, '_read_silver', side_effect=[coll, empty, hbo_empty, empty]):
        with patch('stages.export_visits.Path.mkdir'):
            with patch('stages.export_visits.Path.__truediv__', return_value=MagicMock()) as mock_div:
                with patch('stages.export_visits.Path.write_bytes'):
                    stage.run()

    zip_name_arg = mock_div.call_args[0][0]
    assert 'marvious' in zip_name_arg


# ── zero_fill_mosquito ────────────────────────────────────────────────────────

def _make_coll_row(session_id, hhid='HH1', mrccode='64', date='2026-05-22', clocation='1'):
    return {'session_id': session_id, 'hhid': hhid, 'mrccode': mrccode,
            'dateofcollection': date, 'clocation': clocation}


def test_zero_fill_all_attributes_are_zero_not_nan():
    """Zero-fill rows must have 0 (not NaN) for all mosquito-attribute columns."""
    collection = pd.DataFrame([_make_coll_row('S1')])
    mosquito = pd.DataFrame([
        {'session_id': 'S1', 'chour': '3', 'mosqnum': '1',
         'grossspecies': '1', 'abdstatus': '2', 'mosq_barcode': 'H26-BB-0001'},
    ])
    result = zero_fill_mosquito(mosquito, collection, expected_chours=[3, 4])
    zero_row = result[result['chour'].astype(str) == '4'].iloc[0]
    assert str(zero_row['mosqnum']) == '0'
    assert str(zero_row['grossspecies']) == '0'
    assert str(zero_row['abdstatus']) == '0'
    assert str(zero_row['mosq_barcode']) == '0'


def test_zero_fill_adds_missing_hours():
    """Hours in expected_chours with no mosquito rows get a zero row."""
    collection = pd.DataFrame([_make_coll_row('S1')])
    mosquito = pd.DataFrame([
        {'session_id': 'S1', 'chour': '3', 'mosqnum': '1', 'grossspecies': '1'},
    ])
    result = zero_fill_mosquito(mosquito, collection, expected_chours=list(range(3, 6)))
    # chours 4 and 5 were missing — should now appear with mosqnum=0
    result_chours = set(result['chour'].astype(str))
    assert '3' in result_chours
    assert '4' in result_chours
    assert '5' in result_chours
    zero_rows = result[result['mosqnum'].astype(str) == '0']
    assert len(zero_rows) == 2


def test_zero_fill_does_not_duplicate_existing_rows():
    """Existing mosquito rows are kept unchanged."""
    collection = pd.DataFrame([_make_coll_row('S1')])
    mosquito = pd.DataFrame([
        {'session_id': 'S1', 'chour': '3', 'mosqnum': '2', 'grossspecies': '1'},
        {'session_id': 'S1', 'chour': '3', 'mosqnum': '1', 'grossspecies': '3'},
    ])
    result = zero_fill_mosquito(mosquito, collection, expected_chours=[3, 4])
    # chour 3 has 2 real rows — both stay; chour 4 gets 1 zero row
    assert len(result) == 3
    assert set(result[result['chour'].astype(str) == '3']['mosqnum'].astype(str)) == {'1', '2'}


def test_zero_fill_inherits_session_fields_from_collection():
    """Zero rows carry hhid, mrccode, dateofcollection, clocation from collection."""
    collection = pd.DataFrame([_make_coll_row('S1', hhid='HH99', mrccode='66',
                                               date='2026-05-22', clocation='2')])
    mosquito = pd.DataFrame(columns=['session_id', 'chour', 'mosqnum'])
    result = zero_fill_mosquito(mosquito, collection, expected_chours=[3])
    row = result.iloc[0]
    assert row['hhid'] == 'HH99'
    assert str(row['mrccode']) == '66'
    assert row['clocation'] == '2'


def test_zero_fill_session_with_no_mosquitoes_gets_all_expected_hours():
    """A session with zero mosquitoes gets one zero row per expected chour."""
    collection = pd.DataFrame([_make_coll_row('S1'), _make_coll_row('S2', hhid='HH2')])
    mosquito = pd.DataFrame(columns=['session_id', 'chour', 'mosqnum'])
    result = zero_fill_mosquito(mosquito, collection, expected_chours=[3, 4, 5])
    assert len(result) == 6  # 2 sessions × 3 hours
    assert set(result['session_id']) == {'S1', 'S2'}


def test_marvious_uses_n_collections_from_marvious_config():
    """n_collections from the marvious config block controls how many nights are included."""
    stage = _make_stage(n=1)

    # 2 nights of data per HH — only night 1 should appear with n=1
    coll = _make_collection(['64'])
    empty = pd.DataFrame(columns=['session_id', 'mrccode', 'hhid'])
    hbo_empty = pd.DataFrame(columns=['hhid', 'mrccode', 'session_id', 'dateofobservation'])

    with patch.object(stage, '_read_silver', side_effect=[coll, empty, hbo_empty, empty]):
        with patch('stages.export_visits.Path.mkdir'):
            with patch('stages.export_visits.Path.write_bytes') as mock_write:
                result = stage.run()

    assert result.success
    zf_bytes = mock_write.call_args[0][0]
    with zipfile.ZipFile(io.BytesIO(zf_bytes)) as zf:
        hlc_csv = zf.read('hlc_collection.csv').decode()
    nights = {r.split(',')[2] for r in hlc_csv.strip().splitlines()[1:] if r}
    assert len(nights) == 1
    assert '2026-05-02' not in nights
