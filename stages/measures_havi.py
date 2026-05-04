from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from modules.data_validator import EntomologyValidator
from modules.db import has_table
from stages.base import BaseStage, StageResult

logger = logging.getLogger(__name__)

SQL_MEASURES_DIR = os.path.join(os.path.dirname(__file__), '..', 'sql', 'measures')


def _load_sql_files(directory: str) -> list[Path]:
    return sorted(Path(directory).glob('*.sql'))


def _single_country(*frames: pd.DataFrame) -> str:
    countries: set[str] = set()
    for df in frames:
        if 'country' not in df.columns:
            continue
        values = df['country'].dropna().astype(str).str.strip()
        countries.update(v for v in values if v)
    return next(iter(countries)) if len(countries) == 1 else ''


class MeasuresHavi(BaseStage):
    name = 'measures_havi'
    dependencies: list[str] = ['transform_havi']

    def run(self) -> StageResult:
        def read_silver(table: str) -> pd.DataFrame:
            if not has_table(self.engine, table, schema='silver_havi'):
                logger.info(f"silver_havi.{table} does not exist — treating as empty.")
                return pd.DataFrame()
            return pd.read_sql(f'SELECT * FROM silver_havi."{table}"', self.engine)

        collection_df = read_silver('ento_collection')
        mosquito_df = read_silver('ento_mosquito')
        site_df = read_silver('pheno_site')
        assay_df = read_silver('pheno_assay')
        household_df = read_silver('hbo_household')
        person_df = read_silver('hbo_person')

        if collection_df.empty and assay_df.empty and household_df.empty:
            logger.warning("silver_havi tables are empty — skipping measures.")
            return StageResult(success=True, rows_written=0)

        trial = self.config.get('trial') or {}
        raw_codes = trial.get('valid_mrc_codes')
        valid_mrc_codes = set(raw_codes) if raw_codes else None
        study_start_date = trial.get('study_start_date') or None
        validator = EntomologyValidator(
            valid_mrc_codes=valid_mrc_codes,
            study_start_date=study_start_date,
        )
        errors: list[str] = []
        all_reports: list[pd.DataFrame] = []

        try:
            all_reports.append(validator.validate_collection(collection_df, mosquito_df))
            all_reports.append(validator.validate_mosquito(mosquito_df, collection_df))
            if not assay_df.empty:
                all_reports.append(validator.validate_pheno_assay(assay_df, site_df))
            if not household_df.empty:
                all_reports.append(validator.validate_hbo_household(household_df))
                all_reports.append(validator.validate_hbo_person(person_df, household_df))
        except Exception as exc:
            msg = f"Validation failed: {exc}"
            logger.error(msg)
            errors.append(msg)

        if not all_reports:
            return StageResult(success=False, rows_written=0, errors=errors)

        non_empty_reports = [r for r in all_reports if not r.empty]
        full_report = (
            pd.concat(non_empty_reports, ignore_index=True)
            if non_empty_reports
            else pd.DataFrame(columns=[
                'check', 'severity', 'mrccode', 'field',
                'record_count', 'detail', 'clocation',
            ])
        )
        if 'country' not in full_report.columns:
            fallback_country = _single_country(
                collection_df, mosquito_df, assay_df, site_df, household_df, person_df
            )
            full_report = full_report.assign(country=fallback_country)
        if 'site' not in full_report.columns:
            site_values = full_report['mrccode'] if 'mrccode' in full_report.columns else ''
            full_report = full_report.assign(site=site_values)

        with self.engine.begin() as conn:
            full_report.to_sql(
                'ds_validation_report', conn,
                schema='gold_havi',
                if_exists='replace',
                index=False,
            )

        logger.info(
            f"Wrote {len(full_report)} validation issue(s) → gold_havi.ds_validation_report."
        )

        sql_files = _load_sql_files(SQL_MEASURES_DIR)
        if not sql_files:
            msg = f"No SQL files found in '{SQL_MEASURES_DIR}'."
            logger.warning(msg)
        else:
            with self.engine.begin() as conn:
                for sql_path in sql_files:
                    try:
                        conn.execute(text(sql_path.read_text()))
                        logger.info(f"Executed: {sql_path.name}")
                    except Exception as exc:
                        msg = f"SQL error in '{sql_path.name}': {exc}"
                        logger.error(msg)
                        errors.append(msg)
                        raise

        return StageResult(
            success=len(errors) == 0,
            rows_written=len(full_report),
            errors=errors,
        )
