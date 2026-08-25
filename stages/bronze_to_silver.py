from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text

from modules.db import create_table_indexes, has_table, quote_identifier
from modules.data_cleaner import DataCleaner
from modules.havi_schema import (
    FORM_COLUMNS,
    column_defaults,
    column_definitions,
    logical_dedup_columns,
    primary_key_columns,
    silver_columns,
)
from modules.sqlite_reader import HAVI_TABLES
from stages.base import BaseStage, StageResult

logger = logging.getLogger(__name__)


def _renumber_individualnum(df: pd.DataFrame, affected_sessions: set[str]) -> pd.DataFrame:
    """Reassign individualnum to a contiguous 1..N run per session, for sessions
    that had one or more hbo_person rows removed by a config exclusion.

    Config-driven `exclusions` (see BronzeToSilver.run) can drop a duplicate-
    entry batch (e.g. a mis-dated re-submission) without renumbering the
    survivors, leaving a session's individualnum values starting above 1
    (e.g. 8-14 instead of 1-7). Preserves the relative order of the survivors'
    original individualnum values; only touches sessions that actually had a
    row excluded, so a genuine gap or duplicate elsewhere is left for the
    validator to flag.
    """
    if not affected_sessions or 'session_id' not in df.columns or 'individualnum' not in df.columns:
        return df
    mask = df['session_id'].astype(str).isin(affected_sessions)
    if not mask.any():
        return df
    df = df.copy()
    numeric = pd.to_numeric(df.loc[mask, 'individualnum'], errors='coerce')
    valid_idx = numeric[numeric.notna()].index
    if valid_idx.empty:
        return df
    new_num = (
        numeric.loc[valid_idx]
        .groupby(df.loc[valid_idx, 'session_id'].astype(str))
        .rank(method='first')
        .astype(int)
        .astype(str)
    )
    df.loc[valid_idx, 'individualnum'] = new_num
    return df


def _replace_table(conn, schema: str, table: str, df: pd.DataFrame) -> None:
    """Replace a table through a staging table inside the active transaction."""
    stage_table = f'_stage_{table}'
    columns = list(df.columns)
    conn.execute(text(
        f'DROP TABLE IF EXISTS {quote_identifier(schema)}.{quote_identifier(stage_table)}'
    ))
    conn.execute(text(
        f'CREATE TABLE {quote_identifier(schema)}.{quote_identifier(stage_table)} '
        f'({column_definitions(columns)})'
    ))
    df.to_sql(
        stage_table,
        conn,
        schema=schema,
        if_exists='append',
        index=False,
        method='multi',
        chunksize=1000,
    )
    conn.execute(text(
        f'DROP TABLE IF EXISTS {quote_identifier(schema)}.{quote_identifier(table)}'
    ))
    conn.execute(text(
        f'ALTER TABLE {quote_identifier(schema)}.{quote_identifier(stage_table)} '
        f'RENAME TO {quote_identifier(table)}'
    ))


class BronzeToSilver(BaseStage):
    name = 'bronze_to_silver'
    dependencies: list[str] = ['sqlite_to_bronze']

    def run(self) -> StageResult:
        trial = self.config.get('trial')
        dedup_key = trial['dedup_key']

        total_rows = 0
        errors: list[str] = []
        cleaned_tables: dict[str, pd.DataFrame] = {}

        for table in HAVI_TABLES:
            try:
                if table not in FORM_COLUMNS:
                    continue

                if not has_table(self.engine, table, schema='bronze_havi'):
                    cleaned_tables[table] = pd.DataFrame(columns=silver_columns(table))
                    logger.info(
                        f"[{table}] bronze_havi.{table} does not exist — silver will be empty."
                    )
                    continue

                bronze_df = pd.read_sql(
                    f'SELECT * FROM bronze_havi."{table}"', self.engine
                )
                if bronze_df.empty:
                    cleaned_tables[table] = pd.DataFrame(columns=silver_columns(table))
                    logger.info(
                        f"[{table}] bronze_havi.{table} is empty — silver will be empty."
                    )
                    continue

                logger.info(f"[{table}] {len(bronze_df)} bronze rows.")

                df = bronze_df.copy()

                # Apply config-driven session_id corrections before dedup.
                corrections = (self.config.get('session_id_corrections') or {}).get(table, [])
                if corrections and 'session_id' in df.columns:
                    for correction in corrections:
                        mask = df['session_id'].astype(str) == correction['session_id']
                        if 'clocation' in correction and 'clocation' in df.columns:
                            mask &= df['clocation'].astype(str) == str(correction['clocation'])
                        n = int(mask.sum())
                        if n:
                            df.loc[mask, 'session_id'] = correction['correct_session_id']
                            for field, value in (correction.get('correct_fields') or {}).items():
                                if field in df.columns:
                                    df.loc[mask, field] = value
                            corrected_fields = list(correction.get('correct_fields') or {})
                            extra = f", also correcting {corrected_fields}" if corrected_fields else ""
                            logger.info(
                                f"[{table}] Corrected {n} row(s): session_id "
                                f"'{correction['session_id']}' → '{correction['correct_session_id']}'"
                                f"{extra}."
                            )

                df = DataCleaner(df).drop_exact_duplicates()

                table_key = primary_key_columns(table)
                if table_key != [dedup_key]:
                    df = DataCleaner(df).deduplicate_by_columns(table_key)
                elif dedup_key in df.columns:
                    df = DataCleaner(df).deduplicate_by_uniqueid()
                else:
                    logger.warning(
                        f"[{table}] Dedup key '{dedup_key}' not found — skipping dedup."
                    )

                # Apply config-driven record-level corrections (by uniqueid).
                # Must run before deduplicate_by_lastmod so corrected fields (e.g. mosq_barcode)
                # are in their final state before logical dedup collapses conflicts.
                record_corrections = (self.config.get('record_corrections') or {}).get(table, [])
                if record_corrections and 'uniqueid' in df.columns:
                    for rc in record_corrections:
                        mask = df['uniqueid'].astype(str) == rc['uniqueid']
                        n = int(mask.sum())
                        if n:
                            for field, value in (rc.get('correct_fields') or {}).items():
                                if field in df.columns:
                                    df.loc[mask, field] = value
                            corrected_fields = list(rc.get('correct_fields') or {})
                            logger.info(
                                f"[{table}] Record correction for uniqueid '{rc['uniqueid']}': "
                                f"corrected {corrected_fields}."
                            )

                # Apply config-driven exclusion list before logical dedup so that
                # erroneous records (e.g. datasource=2 placeholders with a newer lastmod)
                # are removed first, allowing the genuine record to survive dedup.
                exclusions = (self.config.get('exclusions') or {}).get(table, [])
                excluded_session_ids: set[str] = set()
                if exclusions and 'uniqueid' in df.columns:
                    excluded_ids = {e['uniqueid'] for e in exclusions if 'uniqueid' in e}
                    if table == 'hbo_person' and 'session_id' in df.columns:
                        excluded_session_ids = set(
                            df.loc[df['uniqueid'].astype(str).isin(excluded_ids), 'session_id']
                            .dropna().astype(str)
                        )
                    before = len(df)
                    df = df[~df['uniqueid'].isin(excluded_ids)]
                    dropped = before - len(df)
                    if dropped:
                        logger.info(
                            f"[{table}] Excluded {dropped} row(s) per config exclusion list."
                        )

                logical_key = logical_dedup_columns(table)
                if logical_key:
                    df = DataCleaner(df).deduplicate_by_lastmod(logical_key)

                # Fill columns absent in older app versions with their default value.
                defaults = column_defaults(table)
                for col, default in defaults.items():
                    if col in df.columns:
                        n = int(df[col].isna().sum())
                        if n:
                            df[col] = df[col].fillna(default)
                            logger.info(
                                f"[{table}] Filled {n} NULL value(s) in '{col}' → '{default}'."
                            )

                if table == 'hbo_person' and excluded_session_ids:
                    df = _renumber_individualnum(df, excluded_session_ids)
                    logger.info(
                        f"[hbo_person] Renumbered individualnum to 1..N for "
                        f"{len(excluded_session_ids)} session(s) affected by exclusions."
                    )

                cleaned_tables[table] = df

            except Exception as exc:
                msg = f"[{table}] Failed during silver processing: {exc}"
                logger.error(msg)
                errors.append(msg)

        if errors:
            return StageResult(success=False, rows_written=0, errors=errors)

        try:
            with self.engine.begin() as conn:
                for table, df in cleaned_tables.items():
                    _replace_table(conn, 'silver_havi', table, df)
                    create_table_indexes(conn, 'silver_havi', table)
                    if df.empty:
                        logger.info(f"[{table}] 0 rows → silver_havi.{table} (emptied).")
                    else:
                        logger.info(f"[{table}] {len(df)} rows → silver_havi.{table}.")
            # Only count rows after the transaction has committed successfully.
            total_rows = sum(len(df) for df in cleaned_tables.values())
        except Exception as exc:
            msg = f"Failed during atomic silver write: {exc}"
            logger.error(msg)
            errors.append(msg)

        return StageResult(
            success=len(errors) == 0,
            rows_written=total_rows,
            errors=errors,
        )
