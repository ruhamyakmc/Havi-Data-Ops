from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stages.export_visits import ExportVisits, _first_n_sessions, build_partial_hhid_report


# ── _first_n_sessions ────────────────────────────────────────────────────────

def test_first_n_sessions_keeps_first_two_nights():
    df = pd.DataFrame({
        'hhid': ['H1', 'H1', 'H1'],
        'dateofcollection': ['2026-05-01', '2026-05-02', '2026-05-03'],
    })
    mask = _first_n_sessions(df, 'dateofcollection', 2)
    assert mask.tolist() == [True, True, False]


def test_first_n_sessions_independent_per_hhid():
    df = pd.DataFrame({
        'hhid': ['H1', 'H1', 'H2', 'H2'],
        'dateofcollection': ['2026-05-01', '2026-05-02', '2026-05-05', '2026-05-06'],
    })
    mask = _first_n_sessions(df, 'dateofcollection', 1)
    assert mask.tolist() == [True, False, True, False]


# ── mrccode filter ───────────────────────────────────────────────────────────

def _make_stage(mrccodes=None):
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        'export': {'n_collections': 2, 'mrccodes': mrccodes} if mrccodes else {'n_collections': 2},
    }.get(key, default)
    engine = MagicMock()
    return ExportVisits(config=config, engine=engine)


def _make_collection(mrccodes):
    return pd.DataFrame({
        'hhid':              [f'{m}HH1' for m in mrccodes],
        'mrccode':           list(mrccodes),
        'dateofcollection':  ['2026-05-01'] * len(mrccodes),
        'session_id':        [f'{m}HH1-2026-05-01-1' for m in mrccodes],
        'datasource':        ['1'] * len(mrccodes),
        'clocation':         ['1'] * len(mrccodes),
        'aspirations_method': ['-6'] * len(mrccodes),
    })


def test_mrccode_filter_excludes_other_sites():
    """When export.mrccodes is set, only those sites appear in the output zip."""
    stage = _make_stage(mrccodes=['64', '66'])

    coll = _make_collection(['64', '66', '70'])
    mosquito = pd.DataFrame(columns=['session_id', 'mrccode', 'hhid'])
    hbo_hh = pd.DataFrame(columns=['hhid', 'mrccode', 'session_id', 'dateofobservation'])
    hbo_person = pd.DataFrame(columns=['session_id', 'hhid'])

    with patch.object(stage, '_read_silver', side_effect=[coll, mosquito, hbo_hh, hbo_person]):
        with patch('stages.export_visits.Path.mkdir'):
            with patch('stages.export_visits.Path.write_bytes') as mock_write:
                result = stage.run()

    assert result.success
    written_bytes = mock_write.call_args[0][0]
    with zipfile.ZipFile(io.BytesIO(written_bytes)) as zf:
        hlc_csv = zf.read('hlc_collection.csv').decode()
    rows = [r for r in hlc_csv.strip().splitlines()[1:] if r]
    mrcs_in_export = {r.split(',')[1] for r in rows}
    assert mrcs_in_export == {'64', '66'}
    assert '70' not in mrcs_in_export


# ── build_partial_hhid_report ─────────────────────────────────────────────────

def _make_hlc_collection(mrc, hhid_nights: dict) -> pd.DataFrame:
    """Build a collection DataFrame where hhid_nights maps hhid → list of dates."""
    rows = []
    for hhid, nights in hhid_nights.items():
        for night in nights:
            rows.append({'hhid': hhid, 'mrccode': mrc, 'dateofcollection': night,
                         'datasource': '1', 'clocation': '1'})
    return pd.DataFrame(rows)


def test_partial_report_identifies_partial_hhid():
    """An hhid with fewer nights than the site maximum is flagged as partial."""
    coll = _make_hlc_collection('69', {
        'HH1': ['2026-05-12', '2026-05-13', '2026-06-08', '2026-06-09'],
        'HH2': ['2026-05-12', '2026-05-13', '2026-06-08', '2026-06-09'],
        'HH3': ['2026-05-12', '2026-05-13'],  # partial — dropped after round 1
        'HH4': ['2026-06-08', '2026-06-09'],  # partial — replacement from round 2
    })
    mrc_sites = {'69': 'Orum HCIV - Otuke'}
    report = build_partial_hhid_report(coll, mrc_sites)
    assert 'HH3' in report
    assert 'HH4' in report
    assert '2026-05-12' in report
    assert '2026-06-08' in report


def test_partial_report_omits_complete_hhids():
    """Households with the maximum night count do not appear in the report."""
    coll = _make_hlc_collection('69', {
        'HH1': ['2026-05-12', '2026-05-13', '2026-06-08', '2026-06-09'],
        'HH2': ['2026-05-12', '2026-05-13', '2026-06-08', '2026-06-09'],
    })
    mrc_sites = {'69': 'Orum HCIV - Otuke'}
    report = build_partial_hhid_report(coll, mrc_sites)
    assert 'HH1' not in report
    assert 'HH2' not in report


def test_partial_report_returns_no_exclusions_message_when_all_complete():
    """If no partial hhids exist, the report says so."""
    coll = _make_hlc_collection('69', {
        'HH1': ['2026-05-12', '2026-05-13'],
        'HH2': ['2026-05-12', '2026-05-13'],
    })
    mrc_sites = {'69': 'Orum HCIV - Otuke'}
    report = build_partial_hhid_report(coll, mrc_sites)
    assert 'No partial' in report or 'no partial' in report or 'none' in report.lower()


def test_zip_name_uses_round_from_config():
    """Zip filename is havi_ento_round{r}_<date>.zip when export.round is set."""
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        'export': {'n_collections': 4, 'round': 2},
    }.get(key, default)
    stage = ExportVisits(config=config, engine=MagicMock())
    name = stage._zip_name(4)
    assert 'round2' in name
    assert 'havi_ento' in name
    assert name.endswith('.zip')


def test_partial_report_language_is_certain():
    """The word 'likely' must not appear — we know which households were replaced."""
    coll = _make_hlc_collection('69', {
        'HH1': ['2026-05-12', '2026-05-13', '2026-06-08', '2026-06-09'],
        'HH2': ['2026-05-12', '2026-05-13'],
    })
    mrc_sites = {'69': 'Orum HCIV - Otuke'}
    report = build_partial_hhid_report(coll, mrc_sites)
    assert 'likely' not in report.lower()


def test_partial_report_includes_site_name():
    """The site name and MRC code appear in the report."""
    coll = _make_hlc_collection('69', {
        'HH1': ['2026-05-12', '2026-05-13', '2026-06-08', '2026-06-09'],
        'HH2': ['2026-05-12', '2026-05-13'],
    })
    mrc_sites = {'69': 'Orum HCIV - Otuke'}
    report = build_partial_hhid_report(coll, mrc_sites)
    assert 'Orum HCIV - Otuke' in report
    assert '69' in report


def test_no_mrccode_filter_exports_all_sites():
    """When export.mrccodes is absent, all sites are exported."""
    stage = _make_stage(mrccodes=None)

    coll = _make_collection(['64', '66', '70'])
    mosquito = pd.DataFrame(columns=['session_id', 'mrccode', 'hhid'])
    hbo_hh = pd.DataFrame(columns=['hhid', 'mrccode', 'session_id', 'dateofobservation'])
    hbo_person = pd.DataFrame(columns=['session_id', 'hhid'])

    with patch.object(stage, '_read_silver', side_effect=[coll, mosquito, hbo_hh, hbo_person]):
        with patch('stages.export_visits.Path.mkdir'):
            with patch('stages.export_visits.Path.write_bytes') as mock_write:
                result = stage.run()

    assert result.success
    written_bytes = mock_write.call_args[0][0]
    with zipfile.ZipFile(io.BytesIO(written_bytes)) as zf:
        hlc_csv = zf.read('hlc_collection.csv').decode()
    rows = [r for r in hlc_csv.strip().splitlines()[1:] if r]
    mrcs_in_export = {r.split(',')[1] for r in rows}
    assert mrcs_in_export == {'64', '66', '70'}
