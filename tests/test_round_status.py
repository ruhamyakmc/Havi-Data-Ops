from datetime import date
import io
import pytest
import pandas as pd
from openpyxl import load_workbook
from stages.round_status import group_rounds, hlc_round_counts, hbo_round_counts, EXPECTED_HH, build_round_status_excel


def test_empty_dates_returns_empty():
    assert group_rounds([]) == []


def test_single_date_returns_one_window():
    d = date(2026, 5, 5)
    assert group_rounds([d]) == [(d, d)]


def test_two_consecutive_dates_same_round():
    d1, d2 = date(2026, 5, 5), date(2026, 5, 6)
    assert group_rounds([d1, d2]) == [(d1, d2)]


def test_gap_over_two_days_splits_rounds():
    d1, d2 = date(2026, 5, 5), date(2026, 6, 2)
    result = group_rounds([d1, d2])
    assert result == [(d1, d1), (d2, d2)]


def test_two_full_rounds():
    dates = [date(2026, 5, 5), date(2026, 5, 6), date(2026, 6, 2), date(2026, 6, 3)]
    result = group_rounds(dates)
    assert result == [(date(2026, 5, 5), date(2026, 5, 6)), (date(2026, 6, 2), date(2026, 6, 3))]


def test_unsorted_input_sorted_before_grouping():
    dates = [date(2026, 6, 2), date(2026, 5, 5)]
    result = group_rounds(dates)
    assert result[0] == (date(2026, 5, 5), date(2026, 5, 5))
    assert result[1] == (date(2026, 6, 2), date(2026, 6, 2))


def test_gap_of_exactly_two_days_stays_same_round():
    d1, d2 = date(2026, 5, 5), date(2026, 5, 7)
    assert group_rounds([d1, d2]) == [(d1, d2)]


def test_gap_of_three_days_splits_rounds():
    d1, d2 = date(2026, 5, 5), date(2026, 5, 8)
    result = group_rounds([d1, d2])
    assert result == [(d1, d1), (d2, d2)]


def _hlc_row(hhid: str, d: date, clocation: int) -> dict:
    return {'hhid': hhid, 'dateofcollection': d, 'clocation': clocation}


def _full_hlc_df(n1: date, n2: date) -> pd.DataFrame:
    """6 HH × 2 nights × 2 clocations = 24 rows — all complete."""
    rows = []
    for i in range(1, EXPECTED_HH + 1):
        hh = f'HH{i:03}'
        for d in (n1, n2):
            rows.append(_hlc_row(hh, d, 1))  # outdoor
            rows.append(_hlc_row(hh, d, 2))  # indoor
    return pd.DataFrame(rows)


def test_hlc_complete_round():
    n1, n2 = date(2026, 6, 18), date(2026, 6, 19)
    df = _full_hlc_df(n1, n2)
    result = hlc_round_counts(df, n1, n2)
    assert result['complete'] is True
    assert result['n1_indoor'] == 6
    assert result['n1_outdoor'] == 6
    assert result['n2_indoor'] == 6
    assert result['n2_outdoor'] == 6
    assert result['n1_date'] == n1
    assert result['n2_date'] == n2


def test_hlc_missing_one_hh_outdoor_night2():
    n1, n2 = date(2026, 6, 18), date(2026, 6, 19)
    df = _full_hlc_df(n1, n2)
    # Remove one HH outdoor record on night 2
    df = df[~((df['hhid'] == 'HH001') & (df['dateofcollection'] == n2) & (df['clocation'] == 1))]
    result = hlc_round_counts(df, n1, n2)
    assert result['complete'] is False
    assert result['n2_outdoor'] == 5
    assert result['n2_indoor'] == 6


def test_hlc_single_night_round():
    n1 = date(2026, 6, 17)
    rows = [_hlc_row(f'HH{i:03}', n1, c) for i in range(1, 7) for c in (1, 2)]
    df = pd.DataFrame(rows)
    result = hlc_round_counts(df, n1, n1)
    assert result['n1_date'] == n1
    assert result['n2_date'] is None
    assert result['n1_indoor'] == 6
    assert result['n2_indoor'] == 0
    assert result['complete'] is False  # only 1 night — can't be complete


def test_hlc_empty_dataframe():
    result = hlc_round_counts(pd.DataFrame(columns=['hhid', 'dateofcollection', 'clocation']), date(2026, 6, 18), date(2026, 6, 19))
    assert result['complete'] is False
    assert result['n1_indoor'] == 0


def _hbo_df(dates_per_hh: dict[str, date]) -> pd.DataFrame:
    return pd.DataFrame([
        {'hhid': hh, 'dateofobservation': d}
        for hh, d in dates_per_hh.items()
    ])


def test_hbo_complete_aligned_to_round():
    round_start, round_end = date(2026, 6, 18), date(2026, 6, 19)
    hbo = _hbo_df({f'HH{i:03}': date(2026, 6, 18) for i in range(1, 7)})
    result = hbo_round_counts(hbo, round_start, round_end)
    assert result['hbo_hh'] == 6
    assert result['hbo_complete'] is True


def test_hbo_incomplete_four_hh():
    round_start, round_end = date(2026, 6, 18), date(2026, 6, 19)
    hbo = _hbo_df({f'HH{i:03}': date(2026, 6, 18) for i in range(1, 5)})
    result = hbo_round_counts(hbo, round_start, round_end)
    assert result['hbo_hh'] == 4
    assert result['hbo_complete'] is False


def test_hbo_aligned_within_3_days_tolerance():
    # HBO submitted 3 days after round end — still aligned
    round_start, round_end = date(2026, 6, 18), date(2026, 6, 19)
    hbo = _hbo_df({f'HH{i:03}': date(2026, 6, 22) for i in range(1, 7)})
    result = hbo_round_counts(hbo, round_start, round_end)
    assert result['hbo_hh'] == 6


def test_hbo_outside_tolerance_returns_empty():
    round_start, round_end = date(2026, 6, 18), date(2026, 6, 19)
    # HBO 10 days later — should not align to this round
    hbo = _hbo_df({f'HH{i:03}': date(2026, 6, 29) for i in range(1, 7)})
    result = hbo_round_counts(hbo, round_start, round_end)
    assert result['hbo_hh'] == 0
    assert result['hbo_complete'] is False
    assert result['hbo_dates'] == ''


def test_hbo_empty_dataframe():
    result = hbo_round_counts(pd.DataFrame(columns=['hhid', 'dateofobservation']), date(2026, 6, 18), date(2026, 6, 19))
    assert result['hbo_hh'] == 0
    assert result['hbo_complete'] is False


def _load_wb(data: bytes):
    return load_workbook(io.BytesIO(data))


def test_excel_has_three_sheets():
    wb = _load_wb(build_round_status_excel([], [], []))
    assert wb.sheetnames == ['Summary', 'Aspirations', 'Incomplete Detail']


def test_excel_summary_headers():
    wb = _load_wb(build_round_status_excel([], [], []))
    ws = wb['Summary']
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    assert 'mrccode' in headers
    assert 'hlc_complete' in headers
    assert 'hbo_complete' in headers


def test_excel_summary_row_written():
    row = {
        'mrccode': '12', 'site': 'Kyatiri', 'round': 1,
        'hlc_dates': '2026-05-19 / 2026-05-20',
        'hlc_n1_indoor': 6, 'hlc_n1_outdoor': 6,
        'hlc_n2_indoor': 6, 'hlc_n2_outdoor': 6,
        'hlc_complete': True,
        'hbo_dates': '2026-05-19', 'hbo_hh': 6, 'hbo_complete': True,
    }
    wb = _load_wb(build_round_status_excel([row], [], []))
    ws = wb['Summary']
    assert ws.max_row == 2  # header + 1 data row
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    mrc_col = headers.index('mrccode') + 1
    assert ws.cell(2, mrc_col).value == '12'


def test_excel_incomplete_detail_headers():
    wb = _load_wb(build_round_status_excel([], [], []))
    ws = wb['Incomplete Detail']
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    assert 'status' in headers
    assert 'clocation' in headers


def test_excel_aspiration_row_written():
    asp = {'mrccode': '64', 'site': 'Busitema', 'asp_dates': '2026-05-22 / 2026-05-23', 'asp_hh': 6}
    wb = _load_wb(build_round_status_excel([], [], [asp]))
    ws = wb['Aspirations']
    assert ws.max_row == 2
