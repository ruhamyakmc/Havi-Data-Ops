from __future__ import annotations

import logging

import pandas as pd

from ._shared import (
    _DEFAULT_VALID_MRC_CODES,
    _REPORT_COLS,
    _clocation,
    _issue,
)

logger = logging.getLogger(__name__)


class _ValidatorBase:
    """Base class: constructor, shared checks used by multiple form validators."""

    def __init__(
        self,
        valid_mrc_codes: set[int] | None = None,
        study_start_date: str | None = None,
    ) -> None:
        self._valid_mrc_codes: frozenset[int] = (
            frozenset(valid_mrc_codes)
            if valid_mrc_codes is not None
            else _DEFAULT_VALID_MRC_CODES
        )
        self._study_start: pd.Timestamp = pd.Timestamp(
            study_start_date if study_start_date else '2026-04-13'
        )

    # ------------------------------------------------------------------
    # Shared checks (called from multiple form validators)
    # ------------------------------------------------------------------

    def _required_fields(self, df: pd.DataFrame, fields: list[str]) -> list[dict]:
        issues = []
        for fname in fields:
            if fname not in df.columns:
                issues.append(_issue(
                    'missing_column', 'ERROR', fname, len(df),
                    f"Column '{fname}' is absent from the dataset.",
                ))
                continue
            null_mask = df[fname].isna() | (df[fname].astype(str).str.strip() == '')
            n = int(null_mask.sum())
            if n:
                issues.append(_issue(
                    'missing_required_field', 'ERROR', fname, n,
                    f"{n} record(s) have no value for required field '{fname}'.",
                    _clocation(df, null_mask),
                    hhid=self._hhids(df, null_mask),
                    session_id=self._session_ids(df, null_mask),
                ))
        return issues

    def _duplicate_uniqueid(self, df: pd.DataFrame) -> list[dict]:
        if 'uniqueid' not in df.columns:
            return []
        col = df['uniqueid'].dropna().astype(str)
        col = col[col.str.strip() != '']
        dup = col.duplicated(keep=False)
        n = int(dup.sum())
        if not n:
            return []
        return [_issue(
            'duplicate_uniqueid', 'ERROR', 'uniqueid', n,
            f"{n} row(s) share a uniqueid with at least one other row "
            f"({col[dup].nunique()} distinct value(s) affected).",
            _clocation(df, col[dup].index),
            hhid=self._hhids(df, col[dup].index),
            session_id=self._session_ids(df, col[dup].index),
        )]

    def _orphan_records(
        self,
        child_df: pd.DataFrame,
        parent_df: pd.DataFrame,
        key: str,
        check_name: str,
    ) -> list[dict]:
        if key not in child_df.columns or parent_df.empty or key not in parent_df.columns:
            return []
        valid_keys = set(parent_df[key].dropna().astype(str))
        child_keys = child_df[key].fillna('').astype(str)
        orphan_mask = ~child_keys.isin(valid_keys)
        n = int(orphan_mask.sum())
        if not n:
            return []
        return [_issue(
            check_name, 'ERROR', key, n,
            f"{n} record(s) have a '{key}' not found in the parent table.",
            _clocation(child_df, orphan_mask),
            hhid=self._hhids(child_df, orphan_mask),
            session_id=self._session_ids(child_df, orphan_mask),
        )]

    def _code_validity(
        self,
        df: pd.DataFrame,
        field: str,
        valid_codes: set,
        check_name: str,
        label: str,
    ) -> list[dict]:
        if field not in df.columns:
            return []
        numeric = pd.to_numeric(df[field], errors='coerce')
        has_val = numeric.notna()
        invalid = has_val & ~numeric.isin(valid_codes)
        n = int(invalid.sum())
        if not n:
            return []
        bad_vals = sorted(v if v != int(v) else int(v) for v in numeric[invalid].unique())
        return [_issue(
            check_name, 'ERROR', field, n,
            f"{n} record(s) have an invalid '{field}' code: {bad_vals}. "
            f"Expected: {label}.",
            _clocation(df, invalid),
            hhid=self._hhids(df, invalid),
            session_id=self._session_ids(df, invalid),
        )]

    def _sparse_columns(self, df: pd.DataFrame) -> list[dict]:
        if df.empty:
            return []
        issues = []
        for col in df.columns:
            if col.startswith('_'):
                continue
            null_ratio = df[col].isna().mean()
            if null_ratio > 0.5:
                n = int(df[col].isna().sum())
                issues.append(_issue(
                    'sparse_column', 'WARNING', col, n,
                    f"Column '{col}' is null in {null_ratio:.1%} of records ({n}/{len(df)}).",
                ))
        return issues

    def _mrccode_validity(self, df: pd.DataFrame) -> list[dict]:
        if 'mrccode' not in df.columns:
            return []
        numeric = pd.to_numeric(df['mrccode'], errors='coerce')
        has_val = numeric.notna()
        invalid = has_val & ~numeric.isin(self._valid_mrc_codes)
        n = int(invalid.sum())
        if not n:
            return []
        bad_vals = sorted(v if v != int(v) else int(v) for v in numeric[invalid].unique())
        return [_issue(
            'invalid_mrccode', 'ERROR', 'mrccode', n,
            f"{n} record(s) have an unrecognised mrccode: {bad_vals}. "
            f"Valid codes: {sorted(self._valid_mrc_codes)}.",
            _clocation(df, invalid),
            hhid=self._hhids(df, invalid),
            session_id=self._session_ids(df, invalid),
        )]

    def _date_future(self, df: pd.DataFrame, field: str, check_name: str) -> list[dict]:
        if field not in df.columns:
            return []
        today = pd.Timestamp.now().normalize()
        dates = pd.to_datetime(df[field], errors='coerce')
        future = dates.notna() & (dates.dt.normalize() > today)
        n = int(future.sum())
        if not n:
            return []
        examples = [str(d.date()) for d in dates[future].dropna().head(5)]
        return [_issue(
            check_name, 'ERROR', field, n,
            f"{n} record(s) have a future {field}. Examples: {examples}.",
            _clocation(df, future),
            hhid=self._hhids(df, future),
            session_id=self._session_ids(df, future),
        )]

    def _date_stale(
        self, df: pd.DataFrame, field: str, check_name: str, days: int = 30
    ) -> list[dict]:
        if field not in df.columns:
            return []
        today = pd.Timestamp.now().normalize()
        cutoff = today - pd.DateOffset(days=days)
        dates = pd.to_datetime(df[field], errors='coerce')
        stale = dates.notna() & (dates.dt.normalize() < cutoff)
        n = int(stale.sum())
        if not n:
            return []
        return [_issue(
            check_name, 'WARNING', field, n,
            f"{n} record(s) have a {field} more than {days} days in the past.",
            _clocation(df, stale),
            hhid=self._hhids(df, stale),
            session_id=self._session_ids(df, stale),
        )]

    def _duration_impossible(self, df: pd.DataFrame) -> list[dict]:
        if 'starttime' not in df.columns or 'stoptime' not in df.columns:
            return []
        start = pd.to_datetime(df['starttime'], errors='coerce')
        stop = pd.to_datetime(df['stoptime'], errors='coerce')
        both = start.notna() & stop.notna()
        impossible = both & (stop < start)
        n = int(impossible.sum())
        if not n:
            return []
        return [_issue(
            'impossible_duration', 'ERROR', 'stoptime', n,
            f"{n} record(s) have stoptime before starttime.",
            _clocation(df, impossible),
            hhid=self._hhids(df, impossible),
            session_id=self._session_ids(df, impossible),
        )]

    def _date_before_study_start(self, df: pd.DataFrame, field: str) -> list[dict]:
        if field not in df.columns:
            return []
        dates = pd.to_datetime(df[field], errors='coerce')
        before = dates.notna() & (dates.dt.normalize() < self._study_start)
        n = int(before.sum())
        if not n:
            return []
        examples = [str(d.date()) for d in dates[before].dropna().head(5)]
        return [_issue(
            'date_before_study_start', 'WARNING', field, n,
            f"{n} record(s) have a {field} before the study start date "
            f"({self._study_start.date()}). Examples: {examples}.",
            _clocation(df, before),
            hhid=self._hhids(df, before),
            session_id=self._session_ids(df, before),
        )]

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _hhids(df: pd.DataFrame, mask) -> str:
        if 'hhid' not in df.columns:
            return ''
        try:
            vals = df.loc[mask, 'hhid'].dropna().astype(str).str.strip()
            vals = vals[vals != '']
            return ', '.join(sorted(vals.unique()))
        except Exception:
            return ''

    @staticmethod
    def _session_ids(df: pd.DataFrame, mask) -> str:
        if 'session_id' not in df.columns:
            return ''
        try:
            vals = df.loc[mask, 'session_id'].dropna().astype(str).str.strip()
            vals = vals[vals != '']
            return ', '.join(sorted(vals.unique()))
        except Exception:
            return ''

    @staticmethod
    def _to_df(issues: list[dict]) -> pd.DataFrame:
        if not issues:
            return pd.DataFrame(columns=_REPORT_COLS)
        df = pd.DataFrame(issues, columns=_REPORT_COLS)
        df = df.assign(
            clocation=df['clocation'].fillna(''),
            mrccode=df['mrccode'].fillna(''),
            hhid=df['hhid'].fillna(''),
            session_id=df['session_id'].fillna(''),
        )
        return df
