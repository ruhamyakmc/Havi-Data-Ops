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
            'clocation': '1',
            'mosqnum': str(i),
            'chour': '5',
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
    mosq = _mosquito(session_id='s1', n=2).drop(columns=['clocation'])
    report = V.validate_collection(df, mosq)
    assert report[report['check'] == 'count_mismatch'].empty
    assert report[report['check'] == 'missing_child_records'].empty


def test_child_count_uses_clocation_specific_session_id():
    df = _collection(
        uniqueid=['uid1', 'uid1'],
        session_id=['s1', 's1'],
        clocation=['1', '2'],
        numfanoph=['2', '1'],
    )
    mosq = pd.concat([
        _mosquito(session_id='s1', n=2).assign(clocation='1'),
        _mosquito(session_id='s1', n=1).assign(clocation='2'),
    ], ignore_index=True)

    report = V.validate_collection(df, mosq)

    assert report[report['check'] == 'count_mismatch'].empty
    assert report[report['check'] == 'missing_child_records'].empty


def test_child_count_datasource2_matches_on_session_id_only():
    """datasource=2 collection records have clocation=NULL; match mosquitoes by session_id alone."""
    df = _collection(
        datasource=['2'],
        clocation=[None],
        numfanoph=['3'],
    )
    mosq = pd.concat([
        _mosquito(session_id='sess1', n=3).assign(clocation=None),
    ], ignore_index=True)
    report = V.validate_collection(df, mosq)
    assert report[report['check'] == 'missing_child_records'].empty
    assert report[report['check'] == 'count_mismatch'].empty


# ── mosquito checks ───────────────────────────────────────────────────────────

def test_orphan_mosquito_record():
    mosq = _mosquito(session_id='orphan_sess', n=1)
    collection = _collection()  # session_id = sess1
    report = V.validate_mosquito(mosq, collection)
    assert not report[report['check'] == 'orphan_mosquito'].empty


def test_mosquito_hhid_matches_parent_no_issue():
    mosq = _mosquito(n=1)
    mosq['hhid'] = '312010595'  # matches _collection() default hhid
    report = V.validate_mosquito(mosq, _collection())
    assert report[report['check'] == 'mosquito_hhid_mismatch'].empty


def test_mosquito_hhid_mismatch_vs_parent():
    """Reproduces the Kigandalo bug: session_id is correctly linked but the
    mosquito row's own hhid field is stale relative to the parent collection record."""
    mosq = _mosquito(n=1)
    mosq['hhid'] = '362030155'
    report = V.validate_mosquito(mosq, _collection(hhid=['362030228']))
    issues = report[report['check'] == 'mosquito_hhid_mismatch']
    assert not issues.empty
    assert issues.iloc[0]['severity'] == 'ERROR'


def test_mosquito_hhid_null_when_parent_has_hhid():
    mosq = _mosquito(n=1)
    mosq['hhid'] = None
    report = V.validate_mosquito(mosq, _collection())
    assert not report[report['check'] == 'mosquito_hhid_null'].empty


def test_invalid_chour():
    mosq = _mosquito(n=1)
    mosq['chour'] = '99'
    report = V.validate_mosquito(mosq, _collection())
    assert not report[report['check'] == 'invalid_chour'].empty


def test_chour_before_6pm():
    mosq = _mosquito(n=1)
    mosq['chour'] = '2'  # 5pm–6pm
    report = V.validate_mosquito(mosq, _collection())
    assert not report[report['check'] == 'chour_before_6pm'].empty


def test_chour_after_6am_flagged():
    mosq = _mosquito(n=1)
    mosq['chour'] = '15'  # 6am–7am
    mosq['aspirations_method'] = '1'  # not exempt
    report = V.validate_mosquito(mosq, _collection())
    assert not report[report['check'] == 'chour_after_6am'].empty


def test_chour_after_6am_exempt_for_aspiration_method_4():
    mosq = _mosquito(n=1)
    mosq['chour'] = '15'  # 6am–7am
    mosq['aspirations_method'] = '4'  # indoor aspiration — exempt
    report = V.validate_mosquito(mosq, _collection())
    assert report[report['check'] == 'chour_after_6am'].empty


def test_chour_in_window_no_flag():
    mosq = _mosquito(n=1)
    mosq['chour'] = '10'  # 1am–2am — well within window
    report = V.validate_mosquito(mosq, _collection())
    assert report[report['check'] == 'chour_before_6pm'].empty
    assert report[report['check'] == 'chour_after_6am'].empty


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


def test_barcode_format_buz_correction_is_valid():
    """BUZ barcodes assigned via record_corrections (e.g. H26-NK1-BUZ001) must pass format check."""
    mosq = _mosquito(n=1)
    mosq['mosq_barcode'] = 'H26-NK1-BUZ001'
    report = V.validate_mosquito(mosq, _collection())
    assert report[report['check'] == 'invalid_barcode_format'].empty


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


# ── hbo_household checks ──────────────────────────────────────────────────────

def _household(**overrides) -> pd.DataFrame:
    base = {
        'uniqueid': ['uid1'],
        'session_id': ['sess1'],
        'mrccode': ['47'],
        'hhid': ['347010021'],
        'dateofobservation': ['2026-04-30'],
        'numsleeprooms': ['2'],
        'numsleepareas': ['2'],
        'numhangbednets': ['1'],
        'numpeople': ['4'],
    }
    base.update(overrides)
    n = max((len(v) for v in base.values() if isinstance(v, list)), default=1)
    expanded = {k: (v if isinstance(v, list) else [v]) for k, v in base.items()}
    expanded = {k: (v * n if len(v) == 1 and n > 1 else v) for k, v in expanded.items()}
    return pd.DataFrame(expanded)


def test_low_device_record_count_equals_number_of_devices():
    """record_count should equal the number of low-count devices, matching the detail string."""
    df = _collection(
        uniqueid=['uid1', 'uid2', 'uid3'],
        session_id=['sess1', 'sess2', 'sess3'],
        _source_db=['device_A', 'device_A', 'device_B'],  # device_A: 2 records, device_B: 1 record
    )
    report = V.validate_collection(df, _mosquito(n=0))
    row = report[report['check'] == 'low_device_record_count']
    assert len(row) == 1
    assert row.iloc[0]['record_count'] == 2  # 2 devices, not 3 records


def test_sleeprooms_inconsistent_record_count_equals_affected_rows():
    """record_count should be the number of session rows flagged, not the number of households."""
    hh = _household(
        uniqueid=['uid1', 'uid2', 'uid3', 'uid4'],
        session_id=['sess1', 'sess2', 'sess3', 'sess4'],
        dateofobservation=['2026-04-30', '2026-05-01', '2026-06-01', '2026-06-02'],
        numsleeprooms=['2', '2', '3', '3'],  # changes from 2 to 3 → 1 household, 4 rows
    )
    report = V.validate_hbo_household(hh)
    row = report[report['check'] == 'sleeprooms_inconsistent_across_visits']
    assert len(row) == 1
    assert row.iloc[0]['record_count'] == 4  # 4 session rows, not 1 household


def test_sleepareas_less_than_sleeprooms_is_allowed():
    hh = _household(numsleeprooms=['9'], numsleepareas=['4'])
    report = V.validate_hbo_household(hh)
    assert report[report['check'] == 'sleepareas_less_than_sleeprooms'].empty


# ── hbo_person checks ────────────────────────────────────────────────────────

def _person(**overrides) -> pd.DataFrame:
    base = {
        'uniqueid': ['puid1'],
        'session_id': ['sess1'],
        'individualnum': ['1'],
    }
    base.update(overrides)
    n = max((len(v) for v in base.values() if isinstance(v, list)), default=1)
    expanded = {k: (v if isinstance(v, list) else [v]) for k, v in base.items()}
    expanded = {k: (v * n if len(v) == 1 and n > 1 else v) for k, v in expanded.items()}
    return pd.DataFrame(expanded)


def test_orphan_hbo_person_record():
    person = _person(session_id=['orphan_sess'])
    household = _household()  # session_id = sess1
    report = V.validate_hbo_person_orphans(person, household)
    assert not report[report['check'] == 'orphan_hbo_person'].empty


def test_orphan_hbo_person_no_issue_when_session_matches():
    person = _person(session_id=['sess1'])
    household = _household()  # session_id = sess1
    report = V.validate_hbo_person_orphans(person, household)
    assert report.empty


def test_validate_hbo_person_no_longer_runs_orphan_check_itself():
    """validate_hbo_person is always called with a per-site pre-filtered person_df
    (see stages/measures_havi.py), so its own orphan check could never fire —
    orphan detection must go through validate_hbo_person_orphans() instead."""
    person = _person(session_id=['orphan_sess'])
    household = _household()  # session_id = sess1
    report = V.validate_hbo_person(person, household)
    assert report[report['check'] == 'orphan_hbo_person'].empty
