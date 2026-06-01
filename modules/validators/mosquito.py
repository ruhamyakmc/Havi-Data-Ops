from __future__ import annotations

import pandas as pd

from ._shared import _BARCODE_RE, _MOSQUITO_REQUIRED, _clocation, _issue


class _MosquitoChecks:
    """ento_mosquito validation checks (17–26)."""

    def validate_mosquito(
        self,
        mosquito_df: pd.DataFrame,
        collection_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Run all ento_mosquito checks. Returns a report DataFrame."""
        if (
            'hhid' not in mosquito_df.columns
            and 'hhid' in collection_df.columns
            and 'session_id' in collection_df.columns
            and 'session_id' in mosquito_df.columns
        ):
            sid_to_hhid = (
                collection_df.dropna(subset=['session_id'])
                .set_index('session_id')['hhid']
                .to_dict()
            )
            mosquito_df = mosquito_df.copy()
            mosquito_df.loc[:, 'hhid'] = mosquito_df['session_id'].map(sid_to_hhid)

        issues: list[dict] = []
        issues += self._required_fields(mosquito_df, _MOSQUITO_REQUIRED)
        issues += self._orphan_records(mosquito_df, collection_df, 'session_id', 'orphan_mosquito')
        issues += self._clocation_vs_parent(mosquito_df, collection_df)
        issues += self._code_validity(mosquito_df, 'chour', set(range(1, 19)), 'invalid_chour', '1-18')
        issues += self._code_validity(mosquito_df, 'grossspecies', set(range(1, 10)),
                                       'invalid_grossspecies', '1-9')
        issues += self._code_validity(mosquito_df, 'abdstatus', {0, 1, 2, 3}, 'invalid_abdstatus', '0-3')
        issues += self._barcode_format(mosquito_df)
        issues += self._barcode_uniqueness(mosquito_df)
        issues += self._duplicate_uniqueid(mosquito_df)
        issues += self._duration_impossible(mosquito_df)
        issues += self._sparse_columns(mosquito_df)
        return self._to_df(issues)

    def _clocation_vs_parent(
        self,
        mosquito_df: pd.DataFrame,
        collection_df: pd.DataFrame,
    ) -> list[dict]:
        """Check that each mosquito record's clocation matches its parent collection record."""
        if 'session_id' not in mosquito_df.columns or mosquito_df.empty:
            return []
        if 'session_id' not in collection_df.columns or 'clocation' not in collection_df.columns:
            return []
        if 'clocation' not in mosquito_df.columns:
            return []

        parent_loc = (
            collection_df[['session_id', 'clocation']]
            .dropna(subset=['session_id'])
            .drop_duplicates(subset=['session_id'])
            .set_index('session_id')['clocation']
            .astype(str)
        )

        merged = mosquito_df[['session_id', 'clocation']].copy()
        merged.loc[:, 'session_id_str'] = merged['session_id'].fillna('').astype(str)
        merged.loc[:, 'parent_clocation'] = merged['session_id_str'].map(parent_loc)

        null_mask = merged['clocation'].isna() & merged['parent_clocation'].notna()
        mismatch_mask = (
            merged['clocation'].notna()
            & merged['parent_clocation'].notna()
            & (merged['clocation'].astype(str) != merged['parent_clocation'])
        )

        issues = []
        n_null = int(null_mask.sum())
        if n_null:
            issues.append(_issue(
                'mosquito_clocation_null', 'WARNING', 'clocation', n_null,
                f"{n_null} mosquito record(s) have no clocation — "
                f"indoor/outdoor assignment cannot be determined.",
                hhid=self._hhids(mosquito_df, null_mask),
                session_id=self._session_ids(mosquito_df, null_mask),
            ))
        n_mismatch = int(mismatch_mask.sum())
        if n_mismatch:
            issues.append(_issue(
                'mosquito_clocation_mismatch', 'ERROR', 'clocation', n_mismatch,
                f"{n_mismatch} mosquito record(s) have a clocation that differs "
                f"from their parent collection record.",
                _clocation(mosquito_df, mismatch_mask),
                hhid=self._hhids(mosquito_df, mismatch_mask),
                session_id=self._session_ids(mosquito_df, mismatch_mask),
            ))
        return issues

    def _barcode_format(self, df: pd.DataFrame) -> list[dict]:
        if 'mosq_barcode' not in df.columns:
            return []
        raw = df['mosq_barcode'].dropna().astype(str)
        raw = raw[raw.str.strip() != '']
        bad = ~raw.str.match(_BARCODE_RE)
        n = int(bad.sum())
        if not n:
            return []
        examples = raw[bad].head(5).tolist()
        return [_issue(
            'invalid_barcode_format', 'ERROR', 'mosq_barcode', n,
            f"{n} barcode(s) do not match H26-{{sitecode}}-{{4digits}}. "
            f"Examples: {examples}.",
            _clocation(df, bad),
        )]

    def _barcode_uniqueness(self, df: pd.DataFrame) -> list[dict]:
        if 'mosq_barcode' not in df.columns:
            return []
        raw = df['mosq_barcode'].dropna().astype(str)
        raw = raw[raw.str.strip() != '']
        dup = raw.duplicated(keep=False)
        n = int(dup.sum())
        if not n:
            return []
        examples = sorted(raw[dup].unique())[:5]
        return [_issue(
            'duplicate_barcode', 'ERROR', 'mosq_barcode', n,
            f"{n} record(s) share a mosq_barcode with at least one other row. "
            f"Examples: {examples}.",
            _clocation(df, raw[dup].index),
        )]
