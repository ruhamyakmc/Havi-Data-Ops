from datetime import date
import pytest
import pandas as pd
from stages.round_status import group_rounds, hlc_round_counts, EXPECTED_HH


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
