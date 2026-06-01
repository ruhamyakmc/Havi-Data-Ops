from __future__ import annotations

import pandas as pd

from ._shared import (
    _HBO_HOUSEHOLD_REQUIRED,
    _HBO_PERSON_REQUIRED,
    _LATE_NIGHT_OBS,
    _OBS_COLUMNS,
    _clocation,
    _issue,
)


class _HboChecks:
    """hbo_household, hbo_person, and cross-form validation checks (34–59)."""

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
        issues += self._hbo_person_count_vs_numpeople(person_df, household_df)
        issues += self._hbo_bednet_under_net_logic(person_df, household_df)
        return self._to_df(issues)

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
        if 'hhid' not in df.columns or 'numsleeprooms' not in df.columns:
            return []
        rooms = pd.to_numeric(df['numsleeprooms'], errors='coerce')
        has_val = rooms.notna() & df['hhid'].notna()
        df_val = df[has_val].copy()
        df_val['_rooms'] = rooms[has_val]
        varying = df_val.groupby('hhid')['_rooms'].nunique()
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

    def _hbo_person_count_vs_numpeople(
        self,
        person_df: pd.DataFrame,
        household_df: pd.DataFrame,
    ) -> list[dict]:
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
