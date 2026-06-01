from __future__ import annotations

import pandas as pd

from ._shared import _ASSAY_REQUIRED, _clocation, _issue


class _PhenoChecks:
    """pheno_assay validation checks (27–33)."""

    def validate_pheno_assay(
        self,
        assay_df: pd.DataFrame,
        site_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Run all pheno_assay checks. Returns a report DataFrame."""
        issues: list[dict] = []
        issues += self._required_fields(assay_df, _ASSAY_REQUIRED)
        issues += self._dead_le_tested(assay_df)
        issues += self._kd_le_tested(assay_df)
        issues += self._pct_consistency(assay_df)
        issues += self._code_validity(assay_df, 'mosqspecies', set(range(1, 10)),
                                       'invalid_mosqspecies', '1-9')
        issues += self._orphan_records(assay_df, site_df, 'site_id', 'orphan_assay')
        issues += self._duplicate_uniqueid(assay_df)
        return self._to_df(issues)

    def _dead_le_tested(self, df: pd.DataFrame) -> list[dict]:
        if 'numdead' not in df.columns or 'numtested' not in df.columns:
            return []
        dead = pd.to_numeric(df['numdead'], errors='coerce')
        tested = pd.to_numeric(df['numtested'], errors='coerce')
        both = dead.notna() & tested.notna()
        bad = both & (dead > tested)
        n = int(bad.sum())
        if not n:
            return []
        return [_issue(
            'dead_exceeds_tested', 'ERROR', 'numdead', n,
            f"{n} record(s) have numdead > numtested.",
            _clocation(df, bad),
        )]

    def _kd_le_tested(self, df: pd.DataFrame) -> list[dict]:
        if 'numkd' not in df.columns or 'numtested' not in df.columns:
            return []
        kd = pd.to_numeric(df['numkd'], errors='coerce')
        tested = pd.to_numeric(df['numtested'], errors='coerce')
        both = kd.notna() & tested.notna()
        bad = both & (kd > tested)
        n = int(bad.sum())
        if not n:
            return []
        return [_issue(
            'kd_exceeds_tested', 'ERROR', 'numkd', n,
            f"{n} record(s) have numkd > numtested.",
            _clocation(df, bad),
        )]

    def _pct_consistency(self, df: pd.DataFrame) -> list[dict]:
        issues = []
        tested = pd.to_numeric(df.get('numtested', pd.Series(dtype=float)), errors='coerce')
        checks = [
            ('numdead', 'pctmortality', 'pct_inconsistency'),
            ('numkd', 'pctkd', 'pct_inconsistency'),
        ]
        for count_col, pct_col, check_name in checks:
            if count_col not in df.columns or pct_col not in df.columns:
                continue
            count = pd.to_numeric(df[count_col], errors='coerce')
            pct_recorded = pd.to_numeric(df[pct_col], errors='coerce')
            usable = count.notna() & tested.notna() & pct_recorded.notna() & (tested > 0)
            pct_calc = (count / tested * 100).where(usable)
            mismatch = usable & ((pct_recorded - pct_calc).abs() > 0.1)
            n = int(mismatch.sum())
            if n:
                issues.append(_issue(
                    check_name, 'WARNING', pct_col, n,
                    f"{n} record(s) have a {pct_col} that does not match "
                    f"({count_col}/numtested)*100 within 0.1%.",
                    _clocation(df, mismatch),
                ))
        return issues
