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
