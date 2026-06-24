from __future__ import annotations

import logging

import pandas as pd

from ._shared import _COLLECTION_REQUIRED, _clocation, _issue

logger = logging.getLogger(__name__)


class _CollectionChecks:
    """ento_collection validation checks (1–16)."""

    def validate_collection(
        self,
        collection_df: pd.DataFrame,
        mosquito_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Run all ento_collection checks. Returns a report DataFrame."""
        issues: list[dict] = []
        issues += self._required_fields(collection_df, _COLLECTION_REQUIRED)
        issues += self._malformed_session_id(collection_df)
        issues += self._mrccode_validity(collection_df)
        issues += self._code_validity(collection_df, 'datasource', {1, 2}, 'invalid_datasource',
                                       '1 (HLC) or 2 (Indoor Aspirations)')
        issues += self._code_validity(collection_df, 'clocation', {1, 2}, 'invalid_clocation',
                                       '1 (Outdoor) or 2 (Indoor)')
        issues += self._counts_nonnegative(collection_df)
        issues += self._date_future(collection_df, 'dateofcollection', 'future_collection_date')
        issues += self._date_before_study_start(collection_df, 'dateofcollection')
        issues += self._duration_impossible(collection_df)
        issues += self._duration_too_long(collection_df, hours=12)
        issues += self._count_vs_children(collection_df, mosquito_df)
        issues += self._duplicate_collection_key(collection_df)
        issues += self._duplicate_session_datasource(collection_df)
        issues += self._device_record_count(collection_df)
        issues += self._collection_date_consistency(collection_df)
        issues += self._count_outliers(collection_df)
        issues += self._sparse_columns(collection_df)
        return self._to_df(issues)

    def _malformed_session_id(self, df: pd.DataFrame) -> list[dict]:
        """Flag session_ids that end in a bare '-' (missing clocation/method suffix)."""
        if 'session_id' not in df.columns:
            return []
        bad = df['session_id'].fillna('').astype(str).str.endswith('-')
        n = int(bad.sum())
        if not n:
            return []
        examples = df.loc[bad, 'session_id'].head(5).tolist()
        return [_issue(
            'malformed_session_id', 'ERROR', 'session_id', n,
            f"{n} record(s) have a session_id ending in '-' (missing clocation or "
            f"aspirations_method suffix). Valid suffixes: -1/-2 (HLC) or -3/-4 (aspirations). "
            f"Examples: {examples}.",
            hhid=self._hhids(df, bad),
            session_id=self._session_ids(df, bad),
        )]

    def _counts_nonnegative(self, df: pd.DataFrame) -> list[dict]:
        issues = []
        for field in ('numfanoph', 'nummanoph', 'numculex'):
            if field not in df.columns:
                continue
            numeric = pd.to_numeric(df[field], errors='coerce')
            negative = numeric.notna() & (numeric < 0)
            n = int(negative.sum())
            if n:
                issues.append(_issue(
                    'negative_count', 'ERROR', field, n,
                    f"{n} record(s) have a negative value for '{field}'.",
                    _clocation(df, negative),
                    hhid=self._hhids(df, negative),
                    session_id=self._session_ids(df, negative),
                ))
        return issues

    def _duration_too_long(self, df: pd.DataFrame, hours: int = 12) -> list[dict]:
        if 'starttime' not in df.columns or 'stoptime' not in df.columns:
            return []
        start = pd.to_datetime(df['starttime'], errors='coerce')
        stop = pd.to_datetime(df['stoptime'], errors='coerce')
        both = start.notna() & stop.notna()
        delta_hours = (stop - start).dt.total_seconds() / 3600
        too_long = both & (delta_hours > hours)
        n = int(too_long.sum())
        if not n:
            return []
        return [_issue(
            'duration_too_long', 'WARNING', 'stoptime', n,
            f"{n} record(s) have a duration exceeding {hours} hours.",
            _clocation(df, too_long),
            hhid=self._hhids(df, too_long),
            session_id=self._session_ids(df, too_long),
        )]

    def _count_vs_children(
        self,
        collection_df: pd.DataFrame,
        mosquito_df: pd.DataFrame,
    ) -> list[dict]:
        if 'session_id' not in collection_df.columns or 'numfanoph' not in collection_df.columns:
            return []

        issues = []

        # datasource=2 (Indoor Aspirations) has no clocation by design — match on session_id only.
        # All other records use the composite session_id+clocation key.
        has_datasource = 'datasource' in collection_df.columns
        is_ds2 = (
            collection_df['datasource'].astype(str) == '2'
            if has_datasource
            else pd.Series(False, index=collection_df.index)
        )
        use_composite = (
            'clocation' in collection_df.columns and 'clocation' in mosquito_df.columns
        )

        # Mosquito counts by session_id alone (used for datasource=2)
        mosq_counts_sid: pd.Series = pd.Series(dtype='int64')
        if not mosquito_df.empty and 'session_id' in mosquito_df.columns:
            mosq_counts_sid = mosquito_df['session_id'].dropna().astype(str).value_counts()

        # Mosquito counts by composite key session_id|clocation (used for datasource=1/unknown)
        mosq_counts_composite: pd.Series = pd.Series(dtype='int64')
        if use_composite and not mosquito_df.empty:
            mosquito_keys = (
                mosquito_df[['session_id', 'clocation']]
                .fillna('').astype(str)
                .agg('|'.join, axis=1)
            )
            mosq_counts_composite = (
                mosquito_keys[mosquito_keys.str.strip('|') != ''].value_counts()
            )

        # Warn about ambiguous sessions only when no clocation column exists
        ambiguous_sessions: set[str] = set()
        if not use_composite:
            duplicated = collection_df['session_id'].fillna('').astype(str).duplicated(keep=False)
            ambiguous_sessions = set(
                collection_df.loc[duplicated, 'session_id'].dropna().astype(str)
            )
        if ambiguous_sessions:
            issues.append(_issue(
                'ambiguous_session', 'WARNING', 'session_id', len(ambiguous_sessions),
                f"{len(ambiguous_sessions)} session(s) have duplicate session_id without "
                f"clocation to disambiguate — count validation skipped for these. "
                f"Examples: {sorted(ambiguous_sessions)[:5]}.",
            ))

        null_declared = collection_df['numfanoph'].isna() if 'numfanoph' in collection_df.columns else pd.Series([], dtype=bool)
        n_null = int(null_declared.sum())
        if n_null:
            issues.append(_issue(
                'null_declared_count', 'WARNING', 'numfanoph', n_null,
                f"{n_null} collection record(s) have a NULL numfanoph — "
                f"declared mosquito count is missing.",
                _clocation(collection_df, null_declared),
            ))

        counts = collection_df.copy(deep=True)
        if ambiguous_sessions:
            counts = counts[
                ~counts['session_id'].fillna('').astype(str).isin(ambiguous_sessions)
            ].copy()
            is_ds2 = is_ds2.loc[counts.index]

        counts = counts.assign(
            session_id_str=counts['session_id'].fillna('').astype(str),
            declared_count=pd.to_numeric(counts['numfanoph'], errors='coerce').fillna(0),
        )

        # Assign lookup key: ds2 rows use session_id; HLC rows use composite key
        if use_composite:
            composite_key = counts[['session_id', 'clocation']].fillna('').astype(str).agg('|'.join, axis=1)
            counts = counts.assign(
                child_count_key=composite_key.where(~is_ds2, counts['session_id_str'])
            )
        else:
            counts = counts.assign(child_count_key=counts['session_id_str'])

        # Vectorised lookup: ds2 rows use session_id counts, HLC rows use composite counts
        sid_looked_up = counts['session_id_str'].map(mosq_counts_sid).fillna(0).astype(int)
        if use_composite:
            composite_looked_up = counts['child_count_key'].map(mosq_counts_composite).fillna(0).astype(int)
            is_ds2_aligned = is_ds2.reindex(counts.index, fill_value=False)
            actual = composite_looked_up.where(~is_ds2_aligned, sid_looked_up)
        else:
            actual = sid_looked_up
        counts = counts.assign(actual_count=actual)
        if 'uniqueid' not in counts.columns:
            counts['uniqueid'] = ''

        unexpected = counts[(counts['declared_count'] == 0) & (counts['actual_count'] > 0)]
        n = len(unexpected)
        if n:
            examples = unexpected[['session_id_str', 'actual_count']].head(5).apply(
                lambda r: f"session_id='{r.session_id_str}' ({int(r.actual_count)} record(s))",
                axis=1,
            ).tolist()
            unexpected_mask = counts.index.isin(unexpected.index)
            issues.append(_issue(
                'unexpected_child_records', 'ERROR', 'numfanoph', n,
                f"{n} collection record(s) have numfanoph=0 but mosquito child records exist. "
                f"Examples: {examples}.",
                _clocation(counts, unexpected_mask),
                hhid=self._hhids(counts, unexpected_mask),
                session_id=self._session_ids(counts, unexpected_mask),
            ))

        missing = counts[(counts['declared_count'] >= 1) & (counts['actual_count'] == 0)]
        n = len(missing)
        if n:
            examples = missing[['session_id_str', 'declared_count']].head(5).apply(
                lambda r: f"session_id='{r.session_id_str}' (declared {int(r.declared_count)})",
                axis=1,
            ).tolist()
            missing_mask = counts.index.isin(missing.index)
            issues.append(_issue(
                'missing_child_records', 'WARNING', 'numfanoph', n,
                f"{n} collection record(s) declare numfanoph >= 1 but have no mosquito records. "
                f"Examples: {examples}.",
                _clocation(counts, missing_mask),
                hhid=self._hhids(counts, missing_mask),
                session_id=self._session_ids(counts, missing_mask),
            ))

        mismatch = counts[
            (counts['declared_count'] >= 1)
            & (counts['actual_count'] > 0)
            & (counts['declared_count'] != counts['actual_count'])
        ]
        n = len(mismatch)
        if n:
            examples = mismatch[['session_id_str', 'declared_count', 'actual_count']].head(5).apply(
                lambda r: (
                    f"session_id='{r.session_id_str}' "
                    f"(declared {int(r.declared_count)}, found {int(r.actual_count)})"
                ),
                axis=1,
            ).tolist()
            mismatch_mask = counts.index.isin(mismatch.index)
            issues.append(_issue(
                'count_mismatch', 'ERROR', 'numfanoph', n,
                f"{n} collection record(s) have numfanoph != actual mosquito row count. "
                f"Examples: {examples}.",
                _clocation(counts, mismatch_mask),
                hhid=self._hhids(counts, mismatch_mask),
                session_id=self._session_ids(counts, mismatch_mask),
            ))

        return issues

    def _duplicate_collection_key(self, df: pd.DataFrame) -> list[dict]:
        key_cols = ['uniqueid', 'clocation']
        if any(col not in df.columns for col in key_cols):
            return self._duplicate_uniqueid(df)
        key_df = df[key_cols].fillna('').astype(str).apply(lambda col: col.str.strip())
        complete = key_df.ne('').all(axis=1)
        dup = complete & key_df.duplicated(subset=key_cols, keep=False)
        n = int(dup.sum())
        if not n:
            return []
        return [_issue(
            'duplicate_collection_key', 'ERROR', 'uniqueid', n,
            f"{n} row(s) share the same ento_collection key "
            f"({', '.join(key_cols)}).",
            _clocation(df, dup),
            hhid=self._hhids(df, dup),
            session_id=self._session_ids(df, dup),
        )]

    def _duplicate_session_datasource(self, df: pd.DataFrame) -> list[dict]:
        key_cols = ['session_id', 'datasource']
        if 'clocation' in df.columns:
            key_cols.append('clocation')
        if any(col not in df.columns for col in key_cols):
            return []
        dup = df.duplicated(subset=key_cols, keep=False)
        n = int(dup.sum())
        if not n:
            return []
        return [_issue(
            'duplicate_session_datasource', 'WARNING', 'session_id', n,
            f"{n} record(s) share the same {' + '.join(key_cols)} combination.",
            _clocation(df, dup),
            hhid=self._hhids(df, dup),
            session_id=self._session_ids(df, dup),
        )]

    def _device_record_count(self, df: pd.DataFrame) -> list[dict]:
        if '_source_db' not in df.columns and 'file_name' not in df.columns:
            return []
        col = '_source_db' if '_source_db' in df.columns else 'file_name'
        counts = df[col].dropna().value_counts()
        low = counts[counts <= 2]
        if low.empty:
            return []
        return [_issue(
            'low_device_record_count', 'WARNING', col, len(low),
            f"{len(low)} device file(s) contributed <= 2 records: {low.index.tolist()}.",
        )]

    def _collection_date_consistency(self, df: pd.DataFrame) -> list[dict]:
        date_col = 'collection_date' if 'collection_date' in df.columns else 'dateofcollection'
        if 'hhid' not in df.columns or date_col not in df.columns:
            return []

        work = df[['hhid', date_col]].copy()
        work.loc[:, date_col] = pd.to_datetime(work[date_col], errors='coerce')
        work = work.dropna(subset=[date_col])
        if work.empty:
            return []

        present = work.drop_duplicates(subset=['hhid', date_col]).copy()
        dates = pd.to_datetime(present[date_col], errors='coerce')
        iso = dates.dt.isocalendar()
        present.loc[:, 'iso_year'] = iso['year'].to_numpy()
        present.loc[:, 'iso_week'] = iso['week'].to_numpy()
        issues = []

        for (iso_year, iso_week), week_grp in present.groupby(['iso_year', 'iso_week']):
            week_hhids = set(week_grp['hhid'].astype(str))
            for date, date_grp in week_grp.groupby(date_col):
                date_hhids = set(date_grp['hhid'].astype(str))
                missing = sorted(week_hhids - date_hhids)
                if missing:
                    issues.append(_issue(
                        'missing_collection_night', 'WARNING', date_col, len(missing),
                        f"{len(missing)} household(s) missing from collection on "
                        f"{pd.Timestamp(date).date()} (week {iso_week}): {missing}.",
                    ))
        return issues

    def _count_outliers(self, df: pd.DataFrame) -> list[dict]:
        if df.empty:
            return []
        if 'hhid' not in df.columns or 'clocation' not in df.columns:
            return []
        issues = []
        for loc_val, loc_label in [('1', 'outdoor'), ('2', 'indoor')]:
            loc_mask = df['clocation'].astype(str) == loc_val
            loc_df = df[loc_mask].copy()
            if loc_df.empty:
                continue
            for field in ('numfanoph', 'nummanoph', 'numculex'):
                if field not in loc_df.columns:
                    continue
                numeric = pd.to_numeric(loc_df[field], errors='coerce')
                loc_df = loc_df.assign(_val=numeric)
                outlier_indices: list = []
                for hhid, hh_grp in loc_df.groupby('hhid'):
                    valid = hh_grp['_val'].dropna()
                    if len(valid) < 10:
                        continue
                    q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
                    iqr = q3 - q1
                    if iqr == 0:
                        continue
                    upper = q3 + 1.5 * iqr
                    outliers = hh_grp.index[hh_grp['_val'].notna() & (hh_grp['_val'] > upper)]
                    outlier_indices.extend(outliers.tolist())
                n = len(outlier_indices)
                if not n:
                    continue
                examples = sorted(
                    numeric[outlier_indices].dropna().unique().astype(int).tolist(),
                    reverse=True,
                )[:5]
                issues.append(_issue(
                    'count_outlier', 'WARNING', field, n,
                    f"{n} {loc_label} record(s) have an unusually high '{field}' count "
                    f"(IQR upper fence, per household). Examples: {examples}.",
                    loc_label,
                ))
        return issues
