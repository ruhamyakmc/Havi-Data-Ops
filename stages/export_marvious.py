from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from stages.export_visits import ExportVisits
from stages.base import StageResult

logger = logging.getLogger(__name__)

# Default expected collection hours (chour encoding: 3=6pm, 4=7pm, ..., 14=5am)
_DEFAULT_HLC_CHOURS  = list(range(3, 15))   # 6pm–6am, 12 hours
_DEFAULT_ASP_CHOURS  = list(range(3, 15))   # same window unless configured otherwise

# Fields to carry from collection into a zero row
_COLLECTION_FIELDS = ['session_id', 'hhid', 'mrccode', 'dateofcollection', 'clocation']


def zero_fill_mosquito(
    mosquito_df: pd.DataFrame,
    collection_df: pd.DataFrame,
    expected_chours: list[int],
) -> pd.DataFrame:
    """Return mosquito_df with a zero row for every (session_id, chour) that is missing.

    Zero rows carry session-level fields from collection_df and have mosqnum=0.
    All other mosquito-specific fields are left as NaN.
    """
    expected_chours_str = [str(h) for h in expected_chours]

    # Build set of (session_id, chour) already present
    if not mosquito_df.empty:
        existing = set(
            zip(
                mosquito_df['session_id'].astype(str),
                mosquito_df['chour'].astype(str),
            )
        )
    else:
        existing = set()

    # Build lookup from session_id to collection fields
    coll_fields = [f for f in _COLLECTION_FIELDS if f in collection_df.columns]
    session_lookup = (
        collection_df[coll_fields]
        .drop_duplicates('session_id')
        .set_index('session_id')
        .to_dict('index')
    )

    # Column template: all mosquito columns defaulting to 0
    all_mosq_cols = list(mosquito_df.columns) if not mosquito_df.empty else []

    zero_rows = []
    for session_id, fields in session_lookup.items():
        for chour in expected_chours_str:
            if (str(session_id), chour) not in existing:
                row = {col: 0 for col in all_mosq_cols}
                row.update({**fields, 'session_id': session_id, 'chour': chour, 'mosqnum': 0})
                zero_rows.append(row)

    if not zero_rows:
        return mosquito_df

    zeros_df = pd.DataFrame(zero_rows)
    result = pd.concat([mosquito_df, zeros_df], ignore_index=True)
    # Sort so real rows come before zero rows within each session/chour
    result = result.sort_values(['session_id', 'chour', 'mosqnum'], ignore_index=True)
    return result


class ExportMarvious(ExportVisits):
    """Export for the three Marvious aspiration sites (MRC 64, 66, 70).

    Reads config from the 'marvious' block instead of 'export', names the
    output zip with 'marvious', and zero-fills mosquito hours with no catches.
    """

    name = 'export_marvious'
    dependencies: list[str] = []

    def _zip_name(self, n: int) -> str:
        return f'havi_marvious_export_{date.today().isoformat()}.zip'

    def _transform_mosquito(
        self, mosquito_df: pd.DataFrame, collection_df: pd.DataFrame, ds: str
    ) -> pd.DataFrame:
        cfg = self.config.get('marvious') or {}
        if ds == '1':
            chours = cfg.get('hlc_chours', _DEFAULT_HLC_CHOURS)
        else:
            chours = cfg.get('asp_chours', _DEFAULT_ASP_CHOURS)
        logger.info(
            "Zero-filling mosquito hours for datasource=%s: %d expected chour(s).",
            ds, len(chours),
        )
        return zero_fill_mosquito(mosquito_df, collection_df, chours)

    def run(self) -> StageResult:
        cfg = self.config.get('marvious') or {}
        _orig_get = self.config.get

        def _patched_get(key, default=None):
            if key == 'export':
                return {
                    'n_collections': cfg.get('n_collections', 2),
                    'mrccodes': cfg.get('mrccodes', ['64', '66', '70']),
                }
            return _orig_get(key, default)

        self.config.get = _patched_get
        try:
            result = super().run()
        finally:
            self.config.get = _orig_get
        return result
