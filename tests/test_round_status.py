from datetime import date
import pytest
from stages.round_status import group_rounds


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
