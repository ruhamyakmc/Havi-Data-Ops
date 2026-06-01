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
        mrc_sites = self.config.get('mrc_sites') or {}
        validator = EntomologyValidator(
            valid_mrc_codes=valid_mrc_codes,
            study_start_date=study_start_date,
        )
        errors: list[str] = []
        all_reports: list[pd.DataFrame] = []

        # Collect mrccodes present across the main entomology and household tables.
        mrccodes: list[str] = sorted({
            str(v)
            for df in [collection_df, household_df]
            for v in (df['mrccode'].dropna().unique() if 'mrccode' in df.columns else [])
        })

        def _by_mrc(df: pd.DataFrame, mrc: str) -> pd.DataFrame:
            if df.empty or 'mrccode' not in df.columns:
                return df
            return df[df['mrccode'].astype(str) == mrc]

        def _person_by_mrc(df: pd.DataFrame, hh: pd.DataFrame) -> pd.DataFrame:
            if df.empty or hh.empty or 'session_id' not in df.columns or 'session_id' not in hh.columns:
                return df
            hh_sessions = set(hh['session_id'].dropna().astype(str))
            return df[df['session_id'].astype(str).isin(hh_sessions)]

        try:
            for mrc in mrccodes:
                site_collection = _by_mrc(collection_df, mrc)
                site_mosquito = _by_mrc(mosquito_df, mrc)
                site_household = _by_mrc(household_df, mrc)
                site_person = _person_by_mrc(person_df, site_household)
                site_assay = _by_mrc(assay_df, mrc)
                site_pheno = _by_mrc(site_df, mrc)

                site_reports: list[pd.DataFrame] = []
                site_reports.append(validator.validate_collection(site_collection, site_mosquito))
                site_reports.append(validator.validate_mosquito(site_mosquito, site_collection))
                if not site_assay.empty:
                    site_reports.append(validator.validate_pheno_assay(site_assay, site_pheno))
                if not site_household.empty:
                    site_reports.append(validator.validate_hbo_household(site_household))
                    site_reports.append(validator.validate_hbo_person(site_person, site_household))

                for report in site_reports:
                    if not report.empty:
                        report['mrccode'] = mrc
                        all_reports.append(report)

        except Exception as exc:
            msg = f"Validation failed: {exc}"
            logger.error(msg)
            errors.append(msg)

        full_report = (
            pd.concat(all_reports, ignore_index=True)
            if all_reports
            else pd.DataFrame(columns=[
                'check', 'severity', 'mrccode', 'field',
                'record_count', 'detail', 'clocation', 'hhid', 'session_id',
            ])
        )
        full_report['site'] = full_report['mrccode'].astype(str).map(mrc_sites).fillna('')
        full_report = full_report[['check', 'severity', 'site', 'mrccode', 'field', 'record_count', 'detail', 'hhid', 'session_id', 'clocation']]

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
