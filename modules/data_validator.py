from __future__ import annotations

"""
data_validator.py — HAVI Entomology
------------------------------------
Validation checks:

ento_collection (16 checks):
 1.  Required fields non-null
 2.  mrccode validity (known MRC codes)
 3.  datasource codes (1–2)
 4.  clocation codes (1–2)
 5.  Mosquito counts non-negative
 6.  dateofcollection not in future
 7.  dateofcollection not before study start date
 8.  Duration impossible (stoptime < starttime)
 9.  Duration too long (> 12 hours)
 10. numfanoph=0 but child records exist
 11. numfanoph >= 1 but no child records
 12. numfanoph != actual child row count
 13. Duplicate collection primary key
 14. Duplicate session_id + datasource + clocation
 15. Device record count <= 2
 16. Sparse columns (>50% null)

ento_mosquito (10 checks):
 18. Required fields non-null
 19. Orphan record (session_id not in ento_collection)
 20. chour codes (1-18)
 21. grossspecies codes (1-9)
 22. abdstatus codes (0-3)
 23. Barcode format (H26-{sitecode}-{4digits})
 24. Barcode uniqueness
 25. Duplicate uniqueid
 26. Duration impossible
 27. Sparse columns

pheno_assay (7 checks):
 28. Required fields non-null
 29. numdead <= numtested
 30. numkd <= numtested
 31. pctmortality / pctkd consistency (within 0.1%)
 32. mosqspecies codes (1-9)
 33. Orphan assay (site_id not in pheno_site)
 34. Duplicate uniqueid

hbo_household (12 checks):
 35. Required fields non-null
 36. mrccode validity
 37. hhid exactly 9 numeric digits
 38. hhid unique per dateofobservation
 39. dateofobservation not future
 40. dateofobservation not before study start
 41. numsleeprooms integer 0–20
 42. numsleepareas integer 0–20, >= numsleeprooms
 43. numhangbednets integer 0–20
 44. numpeople integer 1–15
 45. Duplicate uniqueid
 46. Sparse columns

hbo_person (12 checks):
 47. Required fields non-null
 48. age numeric 0–120 (null allowed)
 49. gender codes (1=Male, 2=Female)
 50. individualnum sequential per session (no gaps/duplicates)
 51. obs_* codes valid (1–5 or null)
 52. Missing observation hours (non-trailing null)
 53. Away entire night (all obs = 5)
 54. Asleep entire night (all obs = 3)
 55. Transition: Under net IN → Near OUT → Under net IN
 56. Infant (age < 1) Away OUT during late night
 57. Orphan person (session_id not in hbo_household)
 58. Duplicate uniqueid

cross-form hbo (2 checks):
 59. Person count != numpeople
 60. numhangbednets=0 but obs=1 (Under net IN)
"""

import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_VALID_MRC_CODES: frozenset[int] = frozenset(
    {12, 23, 25, 29, 31, 36, 37, 40, 42, 47, 56, 59, 62, 64, 66, 69, 70}
)
_BARCODE_RE = re.compile(r'^H26-[A-Z0-9]+-\d{4}$')

_CLOCATION_MAP = {1: 'outdoor', 2: 'indoor'}

_REPORT_COLS = [
    'check', 'severity', 'mrccode', 'field',
    'record_count', 'detail', 'clocation', 'hhid', 'session_id',
]

_COLLECTION_REQUIRED = [
    'uniqueid', 'session_id', 'mrccode', 'hhid',
    'dateofcollection', 'starttime', 'stoptime',
]
_MOSQUITO_REQUIRED = [
    'uniqueid', 'session_id', 'mosqnum', 'chour',
    'grossspecies', 'mosq_barcode', 'starttime', 'stoptime',
]
_ASSAY_REQUIRED = [
    'uniqueid', 'site_id', 'assaynum', 'mosqspecies',
    'numtested', 'numdead', 'numkd',
]

_OBS_COLUMNS = [
    'obs_4_5pm', 'obs_5_6pm', 'obs_6_7pm', 'obs_7_8pm', 'obs_8_9pm',
    'obs_9_10pm', 'obs_10_11pm', 'obs_11pm_12am', 'obs_12_1am', 'obs_1_2am',
    'obs_2_3am', 'obs_3_4am', 'obs_4_5am', 'obs_5_6am', 'obs_6_7am',
    'obs_7_8am', 'obs_8_9am', 'obs_9_10am',
]
_LATE_NIGHT_OBS = [
    'obs_9_10pm', 'obs_10_11pm', 'obs_11pm_12am', 'obs_12_1am',
    'obs_1_2am', 'obs_2_3am', 'obs_3_4am', 'obs_4_5am', 'obs_5_6am',
]
_HBO_HOUSEHOLD_REQUIRED = ['uniqueid', 'session_id', 'mrccode', 'hhid', 'dateofobservation']
_HBO_PERSON_REQUIRED = ['uniqueid', 'session_id', 'individualnum']


def _clocation(df: pd.DataFrame, mask) -> str:
    """Return human-readable clocation label(s) for rows matching mask."""
    if 'clocation' not in df.columns:
        return ''
    try:
        vals = pd.to_numeric(df.loc[mask, 'clocation'], errors='coerce').dropna().astype(int).unique()
        labels = sorted({_CLOCATION_MAP.get(v, str(v)) for v in vals})
        return ' & '.join(labels)
    except Exception as exc:
        logger.warning("_clocation() failed: %s", exc)
        return ''


def _issue(
    check: str,
    severity: str,
    field: str,
    count: int,
    detail: str,
    clocation: str = '',
    mrccode: str = '',
    hhid: str = '',
    session_id: str = '',
) -> dict:
    return {
        'check': check,
        'severity': severity,
        'mrccode': mrccode,
        'field': field,
        'record_count': count,
        'detail': detail,
        'clocation': clocation,
        'hhid': hhid,
        'session_id': session_id,
    }


class EntomologyValidator:
    """Validates HAVI entomology DataFrames (silver layer).

    Args:
        valid_mrc_codes: Set of valid MRC site codes. Defaults to
            ``_DEFAULT_VALID_MRC_CODES``. Pass from config so new field
            sites can be added without a code change.
        study_start_date: ISO date string for the study start (e.g. '2026-04-13').
            Observations before this date are flagged as warnings.
    """

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
    # Public API
    # ------------------------------------------------------------------

    def validate_collection(
        self,
        collection_df: pd.DataFrame,
        mosquito_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Run all ento_collection checks. Returns a report DataFrame."""
        issues: list[dict] = []
        issues += self._required_fields(collection_df, _COLLECTION_REQUIRED)
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
        issues += self._clocation_swap(collection_df, mosquito_df)
        issues += self._duplicate_collection_key(collection_df)
        issues += self._duplicate_session_datasource(collection_df)
        issues += self._device_record_count(collection_df)
        issues += self._collection_date_consistency(collection_df)
        issues += self._count_outliers(collection_df)
        issues += self._sparse_columns(collection_df)
        return self._to_df(issues)

    def validate_mosquito(
        self,
        mosquito_df: pd.DataFrame,
        collection_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Run all ento_mosquito checks. Returns a report DataFrame."""
        # Enrich with hhid from collection so issues can be traced to a household.
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
        issues += self._code_validity(mosquito_df, 'chour', set(range(1, 19)), 'invalid_chour',
                                       '1-18')
        issues += self._code_validity(mosquito_df, 'grossspecies', set(range(1, 10)),
                                       'invalid_grossspecies', '1-9')
        issues += self._code_validity(mosquito_df, 'abdstatus', {0, 1, 2, 3}, 'invalid_abdstatus',
                                       '0-3')
        issues += self._barcode_format(mosquito_df)
        issues += self._barcode_uniqueness(mosquito_df)
        issues += self._duplicate_uniqueid(mosquito_df)
        issues += self._duration_impossible(mosquito_df)
        issues += self._sparse_columns(mosquito_df)
        return self._to_df(issues)

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

    def validate_hbo_household(self, household_df: pd.DataFrame) -> pd.DataFrame:
        """Run all hbo_household checks. Returns a report DataFrame."""
        issues: list[dict] = []
        issues += self._required_fields(household_df, _HBO_HOUSEHOLD_REQUIRED)
        issues += self._mrccode_validity(household_df)
        issues += self._hbo_hhid_format(household_df)
        issues += self._hbo_hhid_unique_per_date(household_df)
        issues += self._date_future(household_df, 'dateofobservation', 'future_obs_date')
        issues += self._date_before_study_start(household_df, 'dateofobservation')
        issues += self._field_integer_range(household_df, 'numsleeprooms', 0, 20, 'WARNING')
        issues += self._numsleepareas_logic(household_df)
        issues += self._numsleeprooms_inconsistent(household_df)
        issues += self._field_integer_range(household_df, 'numhangbednets', 0, 20, 'WARNING')
        issues += self._field_integer_range(household_df, 'numpeople', 1, 15, 'WARNING')
        issues += self._duplicate_uniqueid(household_df)
        issues += self._sparse_columns(household_df)
        return self._to_df(issues)

    def validate_hbo_person(
        self,
        person_df: pd.DataFrame,
        household_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Run all hbo_person checks. Returns a report DataFrame."""
        # Enrich with hhid from household so issues can be traced to a household.
        if (
            'hhid' not in person_df.columns
            and 'hhid' in household_df.columns
            and 'session_id' in household_df.columns
            and 'session_id' in person_df.columns
        ):
            sid_to_hhid = (
                household_df.dropna(subset=['session_id'])
                .set_index('session_id')['hhid']
                .to_dict()
            )
            person_df = person_df.copy()
            person_df.loc[:, 'hhid'] = person_df['session_id'].map(sid_to_hhid)

        issues: list[dict] = []
        issues += self._required_fields(person_df, _HBO_PERSON_REQUIRED)
        issues += self._hbo_age_range(person_df)
        issues += self._code_validity(person_df, 'gender', {1, 2}, 'invalid_gender',
                                      '1 (Male) or 2 (Female)')
        issues += self._individualnum_sequential(person_df)
        issues += self._obs_codes_valid(person_df)
        issues += self._obs_missing_hours(person_df)
        issues += self._obs_away_entire_night(person_df)
        issues += self._obs_asleep_entire_night(person_df)
        issues += self._obs_transition_net_out_net(person_df)
        issues += self._obs_infant_away_night(person_df)
        issues += self._orphan_records(person_df, household_df, 'session_id', 'orphan_hbo_person')
        issues += self._duplicate_uniqueid(person_df)
        # Cross-form checks (59–60)
        issues += self._hbo_person_count_vs_numpeople(person_df, household_df)
        issues += self._hbo_bednet_under_net_logic(person_df, household_df)
        return self._to_df(issues)

    # ------------------------------------------------------------------
    # Shared checks
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

    def _clocation_vs_parent(
        self,
        mosquito_df: pd.DataFrame,
        collection_df: pd.DataFrame,
    ) -> list[dict]:
        """Check that each mosquito record's clocation matches its parent collection record.

        Mosquito records with NULL clocation are also flagged — they are untagged
        as indoor/outdoor and cannot be used in downstream analysis.
        """
        if 'session_id' not in mosquito_df.columns or mosquito_df.empty:
            return []
        if 'session_id' not in collection_df.columns or 'clocation' not in collection_df.columns:
            return []
        if 'clocation' not in mosquito_df.columns:
            return []

        # Build a session_id → clocation lookup from the parent collection.
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

        # NULL clocation on mosquito record.
        null_mask = merged['clocation'].isna() & merged['parent_clocation'].notna()
        # clocation present but mismatched with parent.
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

    # ------------------------------------------------------------------
    # ento_collection-specific checks
    # ------------------------------------------------------------------

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
        key_cols = ['session_id']
        if 'clocation' in collection_df.columns and 'clocation' in mosquito_df.columns:
            key_cols.append('clocation')

        # Flag sessions where session_id appears more than once without clocation to
        # disambiguate — count validation cannot be performed reliably for these.
        ambiguous_sessions: set[str] = set()
        if key_cols == ['session_id']:
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

        # Flag collection records where numfanoph is NULL — cannot validate child counts.
        null_declared = collection_df['numfanoph'].isna() if 'numfanoph' in collection_df.columns else pd.Series([], dtype=bool)
        n_null = int(null_declared.sum())
        if n_null:
            issues.append(_issue(
                'null_declared_count', 'WARNING', 'numfanoph', n_null,
                f"{n_null} collection record(s) have a NULL numfanoph — "
                f"declared mosquito count is missing.",
                _clocation(collection_df, null_declared),
            ))

        mosq_counts = pd.Series(dtype='int64')
        if not mosquito_df.empty and all(col in mosquito_df.columns for col in key_cols):
            if key_cols == ['session_id']:
                mosq_counts = mosquito_df['session_id'].dropna().astype(str).value_counts()
            else:
                mosquito_keys = mosquito_df[key_cols].fillna('').astype(str).agg('|'.join, axis=1)
                mosq_counts = mosquito_keys[mosquito_keys.str.strip('|') != ''].value_counts()

        counts = collection_df.copy(deep=True)
        if ambiguous_sessions:
            counts = counts[
                ~counts['session_id'].fillna('').astype(str).isin(ambiguous_sessions)
            ].copy()
        counts = counts.assign(
            session_id_str=counts['session_id'].fillna('').astype(str),
            declared_count=pd.to_numeric(counts['numfanoph'], errors='coerce').fillna(0),
        )
        if key_cols == ['session_id']:
            counts = counts.assign(child_count_key=counts['session_id_str'])
        else:
            counts = counts.assign(
                child_count_key=counts[key_cols].fillna('').astype(str).agg('|'.join, axis=1)
            )
        counts = counts.assign(
            actual_count=counts['child_count_key'].map(mosq_counts).fillna(0).astype(int)
        )
        if 'uniqueid' not in counts.columns:
            counts['uniqueid'] = ''

        # Check 10: numfanoph=0 but children exist
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

        # Check 11: numfanoph >= 1 but no children
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

        # Check 12: numfanoph != child count
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

    def _clocation_swap(
        self,
        collection_df: pd.DataFrame,
        mosquito_df: pd.DataFrame,
    ) -> list[dict]:
        """Detect likely indoor/outdoor swap: one clocation declares mosquitoes but
        has none, while its paired clocation on the same night has all the records."""
        required = {'hhid', 'session_id', 'clocation', 'numfanoph', 'starttime'}
        if not required.issubset(collection_df.columns):
            return []
        if mosquito_df.empty or 'session_id' not in mosquito_df.columns:
            return []

        col = collection_df.copy()
        col['_date'] = pd.to_datetime(col['starttime'], errors='coerce').dt.date
        col['_declared'] = pd.to_numeric(col['numfanoph'], errors='coerce').fillna(0)
        col['_cloc'] = col['clocation'].astype(str)
        col['_sid'] = col['session_id'].astype(str)

        mosq_counts = mosquito_df['session_id'].astype(str).value_counts()
        col['_actual'] = col['_sid'].map(mosq_counts).fillna(0).astype(int)

        # Need both clocations present for the same (hhid, night).
        paired = col.dropna(subset=['hhid', '_date']).copy()
        night_cloc_counts = paired.groupby(['hhid', '_date'])['_cloc'].nunique()
        both_nights = night_cloc_counts[night_cloc_counts >= 2].index
        paired = paired.set_index(['hhid', '_date']).loc[
            paired.set_index(['hhid', '_date']).index.isin(both_nights)
        ].reset_index()

        if paired.empty:
            return []

        # Within each (hhid, night), flag if one clocation has declared > 0 and
        # actual == 0, while the other clocation has actual > 0.
        swap_sids: list[str] = []
        swap_hhids: list[str] = []
        for (hhid, night), grp in paired.groupby(['hhid', '_date']):
            has_declared_no_records = grp[
                (grp['_declared'] > 0) & (grp['_actual'] == 0)
            ]
            has_records = grp[grp['_actual'] > 0]
            if not has_declared_no_records.empty and not has_records.empty:
                swap_sids.extend(has_declared_no_records['_sid'].tolist())
                swap_sids.extend(has_records['_sid'].tolist())
                swap_hhids.append(str(hhid))

        n = len(set(swap_hhids))
        if not n:
            return []

        swap_sid_str = ', '.join(sorted(set(swap_sids)))
        swap_hhid_str = ', '.join(sorted(set(swap_hhids)))
        return [_issue(
            'clocation_swap', 'ERROR', 'clocation', n,
            f"{n} household night(s) show a likely indoor/outdoor swap: one clocation "
            f"declares mosquitoes but has no records while the paired clocation has all "
            f"records. Affected sessions: {sorted(set(swap_sids))}.",
            hhid=swap_hhid_str,
            session_id=swap_sid_str,
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
            'low_device_record_count', 'WARNING', col, int(low.sum()),
            f"{len(low)} device file(s) contributed <= 2 records: {low.index.tolist()}.",
        )]


    def _collection_date_consistency(self, df: pd.DataFrame) -> list[dict]:
        """Check that all households collected in the same ISO week are present on
        both collection nights.

        Each site visit consists of two consecutive collection nights per week, and
        all households in that week's round should appear on both nights. Households
        from different weeks are not compared against each other.
        """
        date_col = 'collection_date' if 'collection_date' in df.columns else 'dateofcollection'
        if 'hhid' not in df.columns or date_col not in df.columns:
            return []

        work = df[['hhid', date_col]].copy()
        work.loc[:, date_col] = pd.to_datetime(work[date_col], errors='coerce')
        work = work.dropna(subset=[date_col])
        if work.empty:
            return []

        # One row per (hhid, date) regardless of indoor/outdoor.
        present = work.drop_duplicates(subset=['hhid', date_col])
        present = present.copy()
        dates = pd.to_datetime(present[date_col], errors='coerce')
        iso = dates.dt.isocalendar()
        present['iso_year'] = iso['year'].values
        present['iso_week'] = iso['week'].values
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
        """Flag collection records with outlier mosquito counts using the IQR method.

        Checks numfanoph, nummanoph, and numculex separately within each household +
        clocation group. Requires at least 10 records per household per location before
        the IQR fence is applied — with fewer nights the distribution is too sparse for
        outlier detection to be meaningful.
        Flags records above Q3 + 1.5 × IQR as warnings.
        """
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

    # ------------------------------------------------------------------
    # ento_mosquito-specific checks
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # pheno_assay-specific checks
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # hbo_household-specific checks
    # ------------------------------------------------------------------

    def _hbo_hhid_format(self, df: pd.DataFrame) -> list[dict]:
        if 'hhid' not in df.columns:
            return []
        raw = df['hhid'].fillna('').astype(str).str.strip()
        has_val = raw != ''
        bad = has_val & ~raw.str.match(r'^\d{9}$')
        n = int(bad.sum())
        if not n:
            return []
        examples = raw[bad].head(5).tolist()
        return [_issue(
            'invalid_hhid_format', 'ERROR', 'hhid', n,
            f"{n} record(s) have an hhid that is not exactly 9 numeric digits. "
            f"Examples: {examples}.",
            _clocation(df, bad),
            hhid=self._hhids(df, bad),
            session_id=self._session_ids(df, bad),
        )]

    def _hbo_hhid_unique_per_date(self, df: pd.DataFrame) -> list[dict]:
        key_cols = ['hhid', 'dateofobservation']
        if any(col not in df.columns for col in key_cols):
            return []
        dup = df.duplicated(subset=key_cols, keep=False)
        n = int(dup.sum())
        if not n:
            return []
        return [_issue(
            'duplicate_hhid_per_date', 'ERROR', 'hhid', n,
            f"{n} record(s) share the same hhid + dateofobservation combination.",
            _clocation(df, dup),
            hhid=self._hhids(df, dup),
            session_id=self._session_ids(df, dup),
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

    def _field_integer_range(
        self,
        df: pd.DataFrame,
        field: str,
        lo: int,
        hi: int,
        severity: str = 'ERROR',
    ) -> list[dict]:
        if field not in df.columns:
            return []
        numeric = pd.to_numeric(df[field], errors='coerce')
        has_val = numeric.notna()
        bad = has_val & ((numeric < lo) | (numeric > hi))
        n = int(bad.sum())
        if not n:
            return []
        return [_issue(
            f'invalid_{field}', severity, field, n,
            f"{n} record(s) have '{field}' outside valid range {lo}–{hi}.",
            _clocation(df, bad),
            hhid=self._hhids(df, bad),
            session_id=self._session_ids(df, bad),
        )]

    def _numsleepareas_logic(self, df: pd.DataFrame) -> list[dict]:
        if 'numsleepareas' not in df.columns:
            return []
        issues: list[dict] = []
        areas = pd.to_numeric(df['numsleepareas'], errors='coerce')
        has_val = areas.notna()

        bad_range = has_val & ((areas < 0) | (areas > 20))
        n = int(bad_range.sum())
        if n:
            issues.append(_issue(
                'invalid_numsleepareas', 'WARNING', 'numsleepareas', n,
                f"{n} record(s) have 'numsleepareas' outside valid range 0–20.",
                _clocation(df, bad_range),
                hhid=self._hhids(df, bad_range),
                session_id=self._session_ids(df, bad_range),
            ))

        if 'numsleeprooms' in df.columns:
            rooms = pd.to_numeric(df['numsleeprooms'], errors='coerce')
            both = areas.notna() & rooms.notna()
            bad_logic = both & (areas < rooms)
            n = int(bad_logic.sum())
            if n:
                issues.append(_issue(
                    'sleepareas_less_than_sleeprooms', 'ERROR', 'numsleepareas', n,
                    f"{n} record(s) have numsleepareas < numsleeprooms.",
                    _clocation(df, bad_logic),
                    hhid=self._hhids(df, bad_logic),
                    session_id=self._session_ids(df, bad_logic),
                ))
        return issues

    def _numsleeprooms_inconsistent(self, df: pd.DataFrame) -> list[dict]:
        """Flag households where numsleeprooms varies across visits.
        Sleep rooms reflect the physical structure of the house and should
        not change between observation nights.
        """
        if 'hhid' not in df.columns or 'numsleeprooms' not in df.columns:
            return []
        rooms = pd.to_numeric(df['numsleeprooms'], errors='coerce')
        has_val = rooms.notna() & df['hhid'].notna()
        df_val = df[has_val].copy()
        df_val['_rooms'] = rooms[has_val]
        varying = (
            df_val.groupby('hhid')['_rooms']
            .nunique()
        )
        bad_hhids = varying[varying > 1].index
        if bad_hhids.empty:
            return []
        bad_mask = df['hhid'].isin(bad_hhids)
        n = int(bad_hhids.shape[0])
        examples = sorted(bad_hhids.tolist())[:5]
        return [_issue(
            'sleeprooms_inconsistent_across_visits', 'WARNING', 'numsleeprooms', n,
            f"{n} household(s) have different numsleeprooms values across visits "
            f"(sleep rooms should not change). Examples: {examples}.",
            _clocation(df, bad_mask),
            hhid=self._hhids(df, bad_mask),
            session_id=self._session_ids(df, bad_mask),
        )]

    # ------------------------------------------------------------------
    # hbo_person-specific checks
    # ------------------------------------------------------------------

    def _hbo_age_range(self, df: pd.DataFrame) -> list[dict]:
        if 'age' not in df.columns:
            return []
        age = pd.to_numeric(df['age'], errors='coerce')
        has_val = age.notna()
        bad = has_val & ((age < 0) | (age > 120))
        n = int(bad.sum())
        if not n:
            return []
        return [_issue(
            'invalid_age', 'ERROR', 'age', n,
            f"{n} record(s) have age outside valid range 0–120.",
            _clocation(df, bad),
            hhid=self._hhids(df, bad),
            session_id=self._session_ids(df, bad),
        )]

    def _individualnum_sequential(self, df: pd.DataFrame) -> list[dict]:
        if 'session_id' not in df.columns or 'individualnum' not in df.columns:
            return []
        numeric_num = pd.to_numeric(df['individualnum'], errors='coerce')
        df_work = df.assign(_indnum=numeric_num, _sess=df['session_id'].fillna('').astype(str))
        bad_sessions: list[str] = []
        for sess_id, grp in df_work.groupby('_sess'):
            if sess_id == '':
                continue
            nums = sorted(grp['_indnum'].dropna().astype(int).tolist())
            if not nums:
                continue
            # All identical (e.g. all = 1) is a device bug corrected in gold — skip.
            if len(set(nums)) == 1 and len(nums) > 1:
                continue
            if nums != list(range(1, len(nums) + 1)):
                bad_sessions.append(sess_id)
        if not bad_sessions:
            return []
        bad_mask = df_work['_sess'].isin(bad_sessions)
        n = int(bad_mask.sum())
        return [_issue(
            'individualnum_not_sequential', 'WARNING', 'individualnum', n,
            f"{len(bad_sessions)} session(s) have individualnum values that are not "
            f"sequential from 1 (gaps or duplicates). Examples: {bad_sessions[:5]}.",
            _clocation(df, bad_mask),
            hhid=self._hhids(df, bad_mask),
            session_id=self._session_ids(df, bad_mask),
        )]

    def _obs_codes_valid(self, df: pd.DataFrame) -> list[dict]:
        present_cols = [c for c in _OBS_COLUMNS if c in df.columns]
        if not present_cols:
            return []
        issues: list[dict] = []
        valid_codes = {-6, 1, 2, 3, 4, 5}
        for col in present_cols:
            numeric = pd.to_numeric(df[col], errors='coerce')
            has_val = numeric.notna()
            invalid = has_val & ~numeric.isin(valid_codes)
            n = int(invalid.sum())
            if n:
                bad_vals = sorted(v if v != int(v) else int(v) for v in numeric[invalid].unique())
                issues.append(_issue(
                    'invalid_obs_code', 'ERROR', col, n,
                    f"{n} record(s) have an invalid observation code in '{col}': {bad_vals}. "
                    f"Expected: 1–5 or -6 (Not Applicable).",
                    _clocation(df, invalid),
                    hhid=self._hhids(df, invalid),
                    session_id=self._session_ids(df, invalid),
                ))
        return issues

    def _obs_missing_hours(self, df: pd.DataFrame) -> list[dict]:
        present_cols = [c for c in _OBS_COLUMNS if c in df.columns]
        if not present_cols:
            return []
        obs = df[present_cols].apply(pd.to_numeric, errors='coerce')

        def _has_internal_null(row: pd.Series) -> bool:
            vals = row.tolist()
            last_valid = max((i for i, v in enumerate(vals) if pd.notna(v)), default=-1)
            if last_valid <= 0:
                return False
            return any(pd.isna(vals[i]) for i in range(last_valid))

        bad_mask = obs.apply(_has_internal_null, axis=1)
        n = int(bad_mask.sum())
        if not n:
            return []
        return [_issue(
            'obs_missing_hours', 'WARNING', 'obs_*', n,
            f"{n} person record(s) have non-trailing null observation hours (gap in sequence).",
            _clocation(df, bad_mask),
            hhid=self._hhids(df, bad_mask),
            session_id=self._session_ids(df, bad_mask),
        )]

    def _obs_away_entire_night(self, df: pd.DataFrame) -> list[dict]:
        present_cols = [c for c in _OBS_COLUMNS if c in df.columns]
        if not present_cols:
            return []
        obs = df[present_cols].apply(pd.to_numeric, errors='coerce')
        all_away = obs.apply(
            lambda row: row.notna().any() and (row.dropna() == 5).all(), axis=1
        )
        n = int(all_away.sum())
        if not n:
            return []
        return [_issue(
            'away_entire_night', 'WARNING', 'obs_*', n,
            f"{n} person record(s) were recorded Away OUT for all observation hours.",
            _clocation(df, all_away),
            hhid=self._hhids(df, all_away),
            session_id=self._session_ids(df, all_away),
        )]

    def _obs_asleep_entire_night(self, df: pd.DataFrame) -> list[dict]:
        present_cols = [c for c in _OBS_COLUMNS if c in df.columns]
        if not present_cols:
            return []
        obs = df[present_cols].apply(pd.to_numeric, errors='coerce')
        all_asleep = obs.apply(
            lambda row: row.notna().any() and (row.dropna() == 3).all(), axis=1
        )
        n = int(all_asleep.sum())
        if not n:
            return []
        return [_issue(
            'asleep_entire_night', 'WARNING', 'obs_*', n,
            f"{n} person record(s) were recorded Asleep for all observation hours.",
            _clocation(df, all_asleep),
            hhid=self._hhids(df, all_asleep),
            session_id=self._session_ids(df, all_asleep),
        )]

    def _obs_transition_net_out_net(self, df: pd.DataFrame) -> list[dict]:
        """Flag pattern: Under net IN (1) → Near net OUT (2) → Under net IN (1)."""
        present_cols = [c for c in _OBS_COLUMNS if c in df.columns]
        if len(present_cols) < 3:
            return []
        obs = df[present_cols].apply(pd.to_numeric, errors='coerce')

        def _has_pattern(row: pd.Series) -> bool:
            vals = row.tolist()
            for i in range(len(vals) - 2):
                if vals[i] == 1 and vals[i + 1] == 2 and vals[i + 2] == 1:
                    return True
            return False

        bad_mask = obs.apply(_has_pattern, axis=1)
        n = int(bad_mask.sum())
        if not n:
            return []
        return [_issue(
            'obs_transition_net_out_net', 'WARNING', 'obs_*', n,
            f"{n} person record(s) show an Under-net IN → Near net OUT → Under-net IN "
            f"transition across consecutive observation hours.",
            _clocation(df, bad_mask),
            hhid=self._hhids(df, bad_mask),
            session_id=self._session_ids(df, bad_mask),
        )]

    def _obs_infant_away_night(self, df: pd.DataFrame) -> list[dict]:
        """Flag infants (age < 1) recorded Away OUT during late-night hours."""
        if 'age' not in df.columns:
            return []
        present_late = [c for c in _LATE_NIGHT_OBS if c in df.columns]
        if not present_late:
            return []
        age = pd.to_numeric(df['age'], errors='coerce')
        is_infant = age.notna() & (age < 1)
        if not is_infant.any():
            return []
        obs_late = df[present_late].apply(pd.to_numeric, errors='coerce')
        away_at_night = (obs_late == 5).any(axis=1)
        bad_mask = is_infant & away_at_night
        n = int(bad_mask.sum())
        if not n:
            return []
        return [_issue(
            'infant_away_night', 'WARNING', 'age', n,
            f"{n} infant record(s) (age < 1) have Away OUT observation during late-night hours "
            f"(9 pm – 6 am).",
            _clocation(df, bad_mask),
            hhid=self._hhids(df, bad_mask),
            session_id=self._session_ids(df, bad_mask),
        )]

    # ------------------------------------------------------------------
    # cross-form hbo checks
    # ------------------------------------------------------------------

    def _hbo_person_count_vs_numpeople(
        self,
        person_df: pd.DataFrame,
        household_df: pd.DataFrame,
    ) -> list[dict]:
        """Check 59: person count per session != numpeople declared in household."""
        if 'session_id' not in person_df.columns:
            return []
        if 'session_id' not in household_df.columns or 'numpeople' not in household_df.columns:
            return []
        person_counts = person_df['session_id'].dropna().astype(str).value_counts()
        hh_sid = household_df['session_id'].fillna('').astype(str)
        hh_numpeople = pd.to_numeric(household_df['numpeople'], errors='coerce')
        bad_sessions: list[str] = []
        for idx in household_df.index:
            sid = hh_sid.at[idx]
            declared = hh_numpeople.at[idx]
            if sid == '' or pd.isna(declared):
                continue
            actual = int(person_counts.get(sid, 0))
            if actual != int(declared):
                bad_sessions.append(sid)
        if not bad_sessions:
            return []
        bad_mask = person_df['session_id'].fillna('').astype(str).isin(bad_sessions)
        return [_issue(
            'person_count_vs_numpeople', 'ERROR', 'numpeople', len(bad_sessions),
            f"{len(bad_sessions)} session(s) have person record count != numpeople. "
            f"Affected sessions: {bad_sessions[:5]}.",
            _clocation(person_df, bad_mask),
            hhid=self._hhids(person_df, bad_mask),
            session_id=self._session_ids(person_df, bad_mask),
        )]

    def _hbo_bednet_under_net_logic(
        self,
        person_df: pd.DataFrame,
        household_df: pd.DataFrame,
    ) -> list[dict]:
        """Check 60: obs=1 (Under net IN) recorded but household has numhangbednets=0."""
        if 'session_id' not in person_df.columns:
            return []
        if 'session_id' not in household_df.columns or 'numhangbednets' not in household_df.columns:
            return []
        hh_sid = household_df['session_id'].fillna('').astype(str)
        hh_nets = pd.to_numeric(household_df['numhangbednets'], errors='coerce')
        no_nets_sessions = set(hh_sid[hh_nets == 0])
        if not no_nets_sessions:
            return []
        present_obs = [c for c in _OBS_COLUMNS if c in person_df.columns]
        if not present_obs:
            return []
        in_no_net_session = person_df['session_id'].fillna('').astype(str).isin(no_nets_sessions)
        obs = person_df[present_obs].apply(pd.to_numeric, errors='coerce')
        has_under_net = (obs == 1).any(axis=1)
        bad_mask = in_no_net_session & has_under_net
        n = int(bad_mask.sum())
        if not n:
            return []
        return [_issue(
            'under_net_no_bednets', 'ERROR', 'numhangbednets', n,
            f"{n} person record(s) have obs=1 (Under net IN) but the household has "
            f"numhangbednets=0.",
            _clocation(person_df, bad_mask),
            hhid=self._hhids(person_df, bad_mask),
            session_id=self._session_ids(person_df, bad_mask),
        )]

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _hhids(df: pd.DataFrame, mask) -> str:
        """Return sorted unique hhids for rows matching mask, or '' if no hhid column."""
        if 'hhid' not in df.columns:
            return ''
        try:
            vals = df.loc[mask, 'hhid'].dropna().astype(str).str.strip()
            vals = vals[vals != '']
            unique_sorted = sorted(vals.unique())
            return ', '.join(unique_sorted)
        except Exception:
            return ''

    @staticmethod
    def _session_ids(df: pd.DataFrame, mask) -> str:
        """Return sorted unique session_ids for rows matching mask, or '' if no session_id column."""
        if 'session_id' not in df.columns:
            return ''
        try:
            vals = df.loc[mask, 'session_id'].dropna().astype(str).str.strip()
            vals = vals[vals != '']
            unique_sorted = sorted(vals.unique())
            return ', '.join(unique_sorted)
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


# ---------------------------------------------------------------------------
# Legacy alias — kept so existing callers importing DataValidator don't break
# during the transition period. Remove after Task 10 updates all callers.
# ---------------------------------------------------------------------------
DataValidator = EntomologyValidator
