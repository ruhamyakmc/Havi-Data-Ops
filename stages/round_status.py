from __future__ import annotations

import io
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
HBO_TOLERANCE = timedelta(days=3)
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


def hbo_round_counts(df: pd.DataFrame, round_start: date, round_end: date) -> dict:
    """Return HBO HH count aligned to the given HLC round window (±3 days tolerance).

    df must be pre-filtered to one mrccode.
    Columns required: hhid, dateofobservation.
    """
    if df.empty:
        return {'hbo_dates': '', 'hbo_hh': 0, 'hbo_complete': False}

    df = df.copy()
    df.loc[:, '_date'] = pd.to_datetime(df['dateofobservation']).dt.date
    window = df[
        (df['_date'] >= round_start - HBO_TOLERANCE)
        & (df['_date'] <= round_end + HBO_TOLERANCE)
    ]

    if window.empty:
        return {'hbo_dates': '', 'hbo_hh': 0, 'hbo_complete': False}

    hbo_hh = int(window['hhid'].nunique())
    sorted_dates = sorted(window['_date'].unique())
    if len(sorted_dates) == 1:
        hbo_dates = str(sorted_dates[0])
    else:
        hbo_dates = f"{sorted_dates[0]} / {sorted_dates[-1]}"

    return {
        'hbo_dates': hbo_dates,
        'hbo_hh': hbo_hh,
        'hbo_complete': hbo_hh >= EXPECTED_HH,
    }


_SUMMARY_COLS = [
    'mrccode', 'site', 'round', 'hlc_dates',
    'hlc_n1_indoor', 'hlc_n1_outdoor', 'hlc_n2_indoor', 'hlc_n2_outdoor',
    'hlc_complete', 'hbo_dates', 'hbo_hh', 'hbo_complete',
]
_INCOMPLETE_COLS = [
    'mrccode', 'site', 'round', 'collection_type', 'hhid', 'date', 'clocation', 'status',
]
_ASP_COLS = ['mrccode', 'site', 'asp_dates', 'asp_hh']

_HEADER_FILL = PatternFill('solid', fgColor='4F81BD')
_HEADER_FONT = Font(bold=True, color='FFFFFF')
_COMPLETE_FILL = PatternFill('solid', fgColor='C6EFCE')
_INCOMPLETE_FILL = PatternFill('solid', fgColor='FFC7CE')


def _write_sheet(ws, cols: list[str], rows: list[dict]) -> None:
    """Write headers + data rows to a worksheet with basic formatting."""
    for col_idx, col in enumerate(cols, 1):
        cell = ws.cell(1, col_idx, col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions[get_column_letter(col_idx)].width = max(14, len(col) + 2)

    for row_idx, row in enumerate(rows, 2):
        for col_idx, col in enumerate(cols, 1):
            val = row.get(col, '')
            cell = ws.cell(row_idx, col_idx, val)
            if col in ('hlc_complete', 'hbo_complete'):
                cell.fill = _COMPLETE_FILL if val else _INCOMPLETE_FILL


def build_round_status_excel(
    summary_rows: list[dict],
    incomplete_rows: list[dict],
    asp_rows: list[dict],
) -> bytes:
    """Build a three-sheet Excel workbook and return raw bytes."""
    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = 'Summary'
    _write_sheet(ws_summary, _SUMMARY_COLS, summary_rows)

    ws_asp = wb.create_sheet('Aspirations')
    _write_sheet(ws_asp, _ASP_COLS, asp_rows)

    ws_detail = wb.create_sheet('Incomplete Detail')
    _write_sheet(ws_detail, _INCOMPLETE_COLS, incomplete_rows)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
