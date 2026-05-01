from __future__ import annotations

import pandas as pd
import pytest

from modules.data_validator import EntomologyValidator

V = EntomologyValidator()

# ── Helpers ──────────────────────────────────────────────────────────────────

def _collection(**overrides) -> pd.DataFrame:
    base = {
        'uniqueid': ['uid1'],
        'session_id': ['sess1'],
        'mrccode': ['12'],
        'hhid': ['312010595'],
        'dateofcollection': ['2026-04-20'],
        'starttime': ['2026-04-20T20:00:00'],
        'stoptime': ['2026-04-20T22:00:00'],
        'datasource': ['1'],
        'clocation': ['1'],
        'numfanoph': ['3'],
        'nummanoph': ['1'],
        'numculex': ['2'],
    }
    base.update(overrides)
    # Determine the target length from any list-valued key
    n = max((len(v) for v in base.values() if isinstance(v, list)), default=1)
    expanded = {k: (v if isinstance(v, list) else [v]) for k, v in base.items()}
    # Broadcast single-element lists to match the target length
    expanded = {k: (v * n if len(v) == 1 and n > 1 else v) for k, v in expanded.items()}
    return pd.DataFrame(expanded)


def _mosquito(session_id='sess1', n=3) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        rows.append({
            'uniqueid': f'muid{i}',
            'session_id': session_id,
            'mosqnum': str(i),
            'chour': '1',
            'grossspecies': '1',
            'abdstatus': '1',
            'mosq_barcode': f'H26-KM1-{i:04d}',
            'sitecode': 'KM1',
            'starttime': '2026-04-20T20:00:00',
            'stoptime': '2026-04-20T20:05:00',
        })
    return pd.DataFrame(rows)


# ── mrccode checks ────────────────────────────────────────────────────────────

def test_invalid_mrccode_raises_error():
    df = _collection(mrccode=['99'])
    report = V.validate_collection(df, _mosquito())
    errors = report[report['check'] == 'invalid_mrccode']
    assert len(errors) == 1
    assert errors.iloc[0]['severity'] == 'ERROR'


def test_valid_mrccode_no_issue():
    df = _collection(mrccode=['12'])
    report = V.validate_collection(df, _mosquito())
    assert report[report['check'] == 'invalid_mrccode'].empty


# ── datasource / clocation ───────────────────────────────────────────────────

def test_invalid_datasource():
    df = _collection(datasource=['9'])
    report = V.validate_collection(df, _mosquito())
    assert not report[report['check'] == 'invalid_datasource'].empty


def test_invalid_clocation():
    df = _collection(clocation=['5'])
    report = V.validate_collection(df, _mosquito())
    assert not report[report['check'] == 'invalid_clocation'].empty


# ── count consistency ─────────────────────────────────────────────────────────

def test_numfanoph_zero_but_children_exist():
    df = _collection(numfanoph=['0'])
    mosq = _mosquito(n=2)
    report = V.validate_collection(df, mosq)
    assert not report[report['check'] == 'unexpected_child_records'].empty
    assert report[report['check'] == 'unexpected_child_records'].iloc[0]['severity'] == 'ERROR'


def test_numfanoph_mismatch():
    df = _collection(numfanoph=['5'])  # declared 5 but only 3 children
    report = V.validate_collection(df, _mosquito(n=3))
    assert not report[report['check'] == 'count_mismatch'].empty


def test_numfanoph_match_no_issue():
    df = _collection(numfanoph=['3'])
    report = V.validate_collection(df, _mosquito(n=3))
    assert report[report['check'] == 'count_mismatch'].empty
    assert report[report['check'] == 'unexpected_child_records'].empty


def test_numfanoph_positive_no_children_is_warning():
    df = _collection(numfanoph=['2'])
    report = V.validate_collection(df, pd.DataFrame())
    warnings = report[report['check'] == 'missing_child_records']
    assert len(warnings) == 1
    assert warnings.iloc[0]['severity'] == 'WARNING'


# ── dateofcollection ─────────────────────────────────────────────────────────

def test_future_date_is_error():
    df = _collection(dateofcollection=['2099-01-01'])
    report = V.validate_collection(df, pd.DataFrame())
    assert not report[report['check'] == 'future_collection_date'].empty


# ── duplicate collection key ─────────────────────────────────────────────────

def test_duplicate_collection_key_flags_same_uniqueid_and_clocation():
    df = _collection(
        uniqueid=['uid1', 'uid1'],
        session_id=['s1', 's2'],
        clocation=['1', '1'],
    )
    report = V.validate_collection(df, pd.DataFrame())
    assert not report[report['check'] == 'duplicate_collection_key'].empty


def test_collection_allows_same_uniqueid_for_different_clocation():
    df = _collection(
        uniqueid=['uid1', 'uid1'],
        session_id=['s1', 's1'],
        clocation=['1', '2'],
        numfanoph=['1', '1'],
    )
    report = V.validate_collection(df, pd.DataFrame())
    assert report[report['check'] == 'duplicate_collection_key'].empty
    assert report[report['check'] == 'duplicate_session_datasource'].empty


def test_child_count_skips_ambiguous_session_without_mosquito_clocation():
    df = _collection(
        uniqueid=['uid1', 'uid1'],
        session_id=['s1', 's1'],
        clocation=['1', '2'],
        numfanoph=['1', '1'],
    )
    mosq = _mosquito(session_id='s1', n=2)
    report = V.validate_collection(df, mosq)
    assert report[report['check'] == 'count_mismatch'].empty
    assert report[report['check'] == 'missing_child_records'].empty


def test_child_count_uses_clocation_specific_session_id():
    df = _collection(
        uniqueid=['uid1', 'uid1'],
        session_id=['s1_outdoor', 's1_indoor'],
        clocation=['1', '2'],
        numfanoph=['2', '1'],
    )
    mosq = pd.concat([
        _mosquito(session_id='s1_outdoor', n=2),
        _mosquito(session_id='s1_indoor', n=1),
    ], ignore_index=True)

    report = V.validate_collection(df, mosq)

    assert report[report['check'] == 'count_mismatch'].empty
    assert report[report['check'] == 'missing_child_records'].empty


# ── mosquito checks ───────────────────────────────────────────────────────────

def test_orphan_mosquito_record():
    mosq = _mosquito(session_id='orphan_sess', n=1)
    collection = _collection()  # session_id = sess1
    report = V.validate_mosquito(mosq, collection)
    assert not report[report['check'] == 'orphan_mosquito'].empty


def test_invalid_chour():
    mosq = _mosquito(n=1)
    mosq['chour'] = '99'
    report = V.validate_mosquito(mosq, _collection())
    assert not report[report['check'] == 'invalid_chour'].empty


def test_invalid_grossspecies():
    mosq = _mosquito(n=1)
    mosq['grossspecies'] = '10'
    report = V.validate_mosquito(mosq, _collection())
    assert not report[report['check'] == 'invalid_grossspecies'].empty


def test_invalid_abdstatus():
    mosq = _mosquito(n=1)
    mosq['abdstatus'] = '9'
    report = V.validate_mosquito(mosq, _collection())
    assert not report[report['check'] == 'invalid_abdstatus'].empty


def test_barcode_format_valid():
    mosq = _mosquito(n=1)
    mosq['mosq_barcode'] = 'H26-KM1-0001'
    report = V.validate_mosquito(mosq, _collection())
    assert report[report['check'] == 'invalid_barcode_format'].empty


def test_barcode_format_invalid():
    mosq = _mosquito(n=1)
    mosq['mosq_barcode'] = 'BADBARCODE'
    report = V.validate_mosquito(mosq, _collection())
    assert not report[report['check'] == 'invalid_barcode_format'].empty


def test_duplicate_barcode():
    mosq = pd.DataFrame([
        {'uniqueid': 'm1', 'session_id': 'sess1', 'mosqnum': '1',
         'chour': '1', 'grossspecies': '1', 'abdstatus': '1',
         'mosq_barcode': 'H26-KM1-0001', 'sitecode': 'KM1',
         'starttime': '2026-04-20T20:00:00', 'stoptime': '2026-04-20T20:05:00'},
        {'uniqueid': 'm2', 'session_id': 'sess1', 'mosqnum': '2',
         'chour': '2', 'grossspecies': '2', 'abdstatus': '0',
         'mosq_barcode': 'H26-KM1-0001', 'sitecode': 'KM1',  # duplicate
         'starttime': '2026-04-20T20:05:00', 'stoptime': '2026-04-20T20:10:00'},
    ])
    report = V.validate_mosquito(mosq, _collection())
    assert not report[report['check'] == 'duplicate_barcode'].empty


# ── pheno_assay checks ────────────────────────────────────────────────────────

def _site() -> pd.DataFrame:
    return pd.DataFrame({'site_id': ['site1'], 'uniqueid': ['suid1']})


def _assay(**overrides) -> pd.DataFrame:
    base = {
        'uniqueid': ['auid1'],
        'site_id': ['site1'],
        'assaynum': ['1'],
        'mosqspecies': ['1'],
        'numtested': ['50'],
        'numdead': ['20'],
        'numkd': ['30'],
        'pctmortality': ['40.0'],
        'pctkd': ['60.0'],
    }
    base.update(overrides)
    return pd.DataFrame({k: [v] if not isinstance(v, list) else v for k, v in base.items()})


def test_numdead_exceeds_numtested():
    df = _assay(numdead=['60'], numtested=['50'])
    report = V.validate_pheno_assay(df, _site())
    assert not report[report['check'] == 'dead_exceeds_tested'].empty


def test_numkd_exceeds_numtested():
    df = _assay(numkd=['60'], numtested=['50'])
    report = V.validate_pheno_assay(df, _site())
    assert not report[report['check'] == 'kd_exceeds_tested'].empty


def test_pct_consistency_mismatch():
    # numdead=20, numtested=50 → pctmortality should be 40.0, not 99.9
    df = _assay(pctmortality=['99.9'])
    report = V.validate_pheno_assay(df, _site())
    assert not report[report['check'] == 'pct_inconsistency'].empty


def test_orphan_assay():
    df = _assay(site_id=['missing_site'])
    report = V.validate_pheno_assay(df, _site())
    assert not report[report['check'] == 'orphan_assay'].empty


def test_invalid_mosqspecies_in_assay():
    df = _assay(mosqspecies=['99'])
    report = V.validate_pheno_assay(df, _site())
    assert not report[report['check'] == 'invalid_mosqspecies'].empty
