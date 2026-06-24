from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from stages.base import BaseStage, StageResult

logger = logging.getLogger(__name__)

EXPECTED_HH = 6
GAP_THRESHOLD = timedelta(days=2)
OUTPUT_PATH = Path('Output') / 'havi_round_status.xlsx'
ASPIRATION_MRCCODES = {'64', '66', '70'}


def group_rounds(dates: list[date]) -> list[tuple[date, date]]:
    """Group a list of dates into round windows where gap > 2 days starts a new round.

    Returns list of (first_date, last_date) tuples in chronological order.
    """
    if not dates:
        return []
    sorted_dates = sorted(set(dates))
    rounds: list[tuple[date, date]] = []
    window_start = sorted_dates[0]
    window_end = sorted_dates[0]
    for d in sorted_dates[1:]:
        if d - window_end > GAP_THRESHOLD:
            rounds.append((window_start, window_end))
            window_start = d
        window_end = d
    rounds.append((window_start, window_end))
    return rounds


def hlc_round_counts(df: pd.DataFrame, round_start: date, round_end: date) -> dict:
    """Return per-night, per-clocation HH counts for an HLC round window.

    df must be pre-filtered to one mrccode and datasource=1.
    Columns required: hhid, dateofcollection, clocation.
    """
    window = df[
        (pd.to_datetime(df['dateofcollection']).dt.date >= round_start)
        & (pd.to_datetime(df['dateofcollection']).dt.date <= round_end)
    ].copy()
    window.loc[:, '_date'] = pd.to_datetime(window['dateofcollection']).dt.date
    window.loc[:, 'clocation'] = pd.to_numeric(window['clocation'], errors='coerce')

    nights = sorted(window['_date'].unique())
    n1_date = nights[0] if len(nights) >= 1 else None
    n2_date = nights[1] if len(nights) >= 2 else None

    def _hh_count(night: date | None, cloc: int) -> int:
        if night is None:
            return 0
        return int(window[(window['_date'] == night) & (window['clocation'] == cloc)]['hhid'].nunique())

    n1_indoor = _hh_count(n1_date, 2)
    n1_outdoor = _hh_count(n1_date, 1)
    n2_indoor = _hh_count(n2_date, 2)
    n2_outdoor = _hh_count(n2_date, 1)

    complete = (
        n2_date is not None
        and n1_indoor == EXPECTED_HH
        and n1_outdoor == EXPECTED_HH
        and n2_indoor == EXPECTED_HH
        and n2_outdoor == EXPECTED_HH
    )

    return {
        'n1_date': n1_date,
        'n2_date': n2_date,
        'n1_indoor': n1_indoor,
        'n1_outdoor': n1_outdoor,
        'n2_indoor': n2_indoor,
        'n2_outdoor': n2_outdoor,
        'complete': complete,
    }
