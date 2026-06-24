from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# System code used by the tablet software to denote a question was skipped
# via built-in skip logic.  Not defined in the XML spec but present in data.
SYSTEM_SKIP_CODE = -9


def _sort_latest(df: pd.DataFrame, preferred_time_col: str) -> pd.DataFrame:
    """Sort newest first using parsed timestamps, with stable fallbacks."""
    sort_cols = []
    ascending = []
    work = df.copy()

    if preferred_time_col in work.columns:
        parsed_col = f'_{preferred_time_col}_parsed'
        work.loc[:, parsed_col] = pd.to_datetime(
            work[preferred_time_col], errors='coerce', utc=True,
        )
        sort_cols.append(parsed_col)
        ascending.append(False)

    if preferred_time_col != 'extracted_at' and 'extracted_at' in work.columns:
        work.loc[:, '_extracted_at_parsed'] = pd.to_datetime(
            work['extracted_at'], errors='coerce', utc=True,
        )
        sort_cols.append('_extracted_at_parsed')
        ascending.append(False)

    for fallback in ('file_name', 'uniqueid'):
        if fallback in work.columns:
            sort_cols.append(fallback)
            ascending.append(False)

    if sort_cols:
        work = work.sort_values(sort_cols, ascending=ascending, na_position='last')
    helper_cols = [c for c in work.columns if c.startswith('_') and c.endswith('_parsed')]
    return work.drop(columns=helper_cols)


class DataCleaner:
    def __init__(self, df: pd.DataFrame):
        self.df = df

    def drop_exact_duplicates(self) -> pd.DataFrame:
        """
        Return a new DataFrame with exact duplicate rows removed.
        Does NOT mutate self.df — the original is preserved.
        """
        compare_cols = [c for c in self.df.columns if c != '_source_db']
        cleaned = self.df.drop_duplicates(subset=compare_cols)
        dropped = len(self.df) - len(cleaned)
        logger.info(f"Dropped {dropped} exact duplicate rows ({len(cleaned)} remaining).")
        return cleaned

    def deduplicate_by_lastmod(self, key_columns: list[str]) -> pd.DataFrame:
        """
        Deduplicate records by a logical key, keeping the most recently modified
        version (latest lastmod). Handles both exact re-syncs across archives and
        genuine field edits where the operator corrected a record.
        Rows missing any key value are retained as-is.
        """
        missing = [c for c in key_columns if c not in self.df.columns]
        if missing:
            logger.warning(
                f"Logical dedup key column(s) missing: {missing}; skipping."
            )
            return self.df.copy()

        df = self.df.copy()
        has_key = pd.Series(True, index=df.index)
        for col in key_columns:
            has_key &= df[col].notna() & (df[col].astype(str).str.strip() != '')

        with_key = df[has_key].copy()
        without_key = df[~has_key]

        if with_key.empty:
            return df

        if 'lastmod' in with_key.columns:
            with_key = _sort_latest(with_key, 'lastmod')

        deduped = with_key.drop_duplicates(subset=key_columns, keep='first')
        dropped = len(with_key) - len(deduped)
        logger.info(
            f"Deduplication by {key_columns} (latest lastmod): removed {dropped} "
            f"duplicate row(s) ({len(deduped)} unique records retained)."
        )
        return pd.concat([deduped, without_key], ignore_index=True)

    def deduplicate_by_uniqueid(self) -> pd.DataFrame:
        """
        Deduplicate records by *uniqueid*, the system-assigned unique survey
        session identifier.  When the same uniqueid appears multiple times
        (e.g. because a field edit caused the file to be re-ingested), the
        most recently extracted copy is kept.
        """
        df = self.df.copy()

        has_uid = df['uniqueid'].notna() & (df['uniqueid'].astype(str).str.strip() != '')
        with_uid = df[has_uid].copy()
        without_uid = df[~has_uid]

        if with_uid.empty:
            logger.info("No uniqueid values found; skipping uniqueid deduplication.")
            return df

        # Sort by extracted_at descending so the newest version of each record wins
        if 'extracted_at' in with_uid.columns:
            with_uid_sorted = _sort_latest(with_uid, 'extracted_at')
        else:
            with_uid_sorted = with_uid
        deduped = with_uid_sorted.drop_duplicates(subset=['uniqueid'], keep='first')

        before = len(with_uid)
        after = len(deduped)
        logger.info(
            f"Deduplication by uniqueid: removed {before - after} duplicate row(s) "
            f"({after} unique records retained; {len(without_uid)} rows had no uniqueid)."
        )

        return pd.concat([deduped, without_uid], ignore_index=True)

    def deduplicate_by_columns(self, columns: list[str]) -> pd.DataFrame:
        """
        Deduplicate records by a table-specific identity key. Rows missing any
        key value are retained because they cannot be safely collapsed.
        """
        missing = [col for col in columns if col not in self.df.columns]
        if missing:
            logger.warning(
                f"Dedup key column(s) missing: {missing}; skipping composite deduplication."
            )
            return self.df.copy()

        df = self.df.copy()
        has_key = pd.Series(True, index=df.index)
        for col in columns:
            has_key &= df[col].notna() & (df[col].astype(str).str.strip() != '')

        with_key = df[has_key].copy()
        without_key = df[~has_key]

        if with_key.empty:
            logger.info("No complete dedup key values found; skipping composite deduplication.")
            return df

        if 'extracted_at' in with_key.columns:
            with_key = _sort_latest(with_key, 'extracted_at')

        deduped = with_key.drop_duplicates(subset=columns, keep='first')
        logger.info(
            f"Deduplication by {columns}: removed {len(with_key) - len(deduped)} "
            f"duplicate row(s) ({len(deduped)} unique records retained; "
            f"{len(without_key)} rows had incomplete keys)."
        )
        return pd.concat([deduped, without_key], ignore_index=True)

    def filter_by_countrycode(self, expected_code: int) -> pd.DataFrame:
        """
        Retain only rows whose *countrycode* matches *expected_code*.
        Rows with a missing or non-matching countrycode are logged and dropped.

        This prevents cross-country record contamination where one country's
        tablets accidentally contain records belonging to another country.

        Returns a new DataFrame; does NOT mutate self.df.
        """
        if 'countrycode' not in self.df.columns:
            logger.warning("'countrycode' column not found; skipping country filter.")
            return self.df.copy()

        country_col = pd.to_numeric(self.df['countrycode'], errors='coerce')
        match = country_col == expected_code
        filtered = self.df[match].copy()
        dropped = len(self.df) - len(filtered)
        if dropped > 0:
            logger.warning(
                f"Dropped {dropped} row(s) whose countrycode != {expected_code} "
                f"(cross-country contamination)."
            )
        return filtered
