from __future__ import annotations

import glob as glob_module
import logging
import os
from pathlib import Path
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
import pandas as pd
from sqlalchemy import text

from modules.config import get_country_paths
from modules.havi_schema import FORM_COLUMNS, bronze_columns, ensure_empty_table
from modules.sqlite_reader import read_sqlite_tables
from stages.base import BaseStage, StageResult

logger = logging.getLogger(__name__)

def _create_meta_table(conn) -> None:
    conn.execute(text(
        'CREATE TABLE IF NOT EXISTS bronze_havi.meta ('
        'run_uuid TEXT, '
        'file_name TEXT, '
        'file_path TEXT, '
        'country TEXT, '
        'community TEXT, '
        'extracted_at TIMESTAMPTZ, '
        'last_modified TIMESTAMPTZ, '
        'loaded BOOLEAN'
        ')'
    ))


def _prepare_bronze_tables(conn) -> None:
    for table_name in FORM_COLUMNS:
        ensure_empty_table(
            conn,
            schema='bronze_havi',
            table=table_name,
            columns=bronze_columns(table_name),
        )
        conn.execute(text(f'TRUNCATE TABLE bronze_havi."{table_name}"'))
    _create_meta_table(conn)
    conn.execute(text('TRUNCATE TABLE bronze_havi.meta'))


def _read_sqlite_from_zip(zip_path: str) -> dict[str, pd.DataFrame]:
    """Read the first SQLite member without trusting ZIP member paths."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        sqlite_names = [
            n for n in zf.namelist()
            if not n.endswith('/') and Path(n).name.endswith('.sqlite')
        ]
        if not sqlite_names:
            raise ValueError(f"No .sqlite file found in {os.path.basename(zip_path)}")

        member = sqlite_names[0]
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / Path(member).name
            db_path.write_bytes(zf.read(member))
            return read_sqlite_tables(str(db_path))


class SqliteToBronze(BaseStage):
    name = 'sqlite_to_bronze'
    dependencies: list[str] = ['ftp_to_extracted']

    def run(self) -> StageResult:
        communities = self.config.get('communities')

        country_community: dict[str, str] = {
            c['country']: c['community_name'] for c in communities.values()
        }

        total_rows = 0
        errors: list[str] = []
        warnings: list[dict] = []

        work_items: list[tuple[str, str, str]] = []
        for country, community_name in sorted(country_community.items()):
            paths = get_country_paths(country)
            extract_path = paths['extract_path']

            zip_files = sorted(
                glob_module.glob(os.path.join(extract_path, 'havi_entomology_*.zip'))
                + glob_module.glob(os.path.join(extract_path, 'Havi_Entomology_*.zip'))
            )
            logger.info(f"[{country}] {len(zip_files)} zip file(s) to process.")
            work_items.extend((zip_path, country, community_name) for zip_path in zip_files)

        try:
            with self.engine.begin() as conn:
                _prepare_bronze_tables(conn)
                for zip_path, country, community_name in work_items:
                    n, file_warnings = self._ingest_zip(
                        conn, zip_path, country, community_name,
                    )
                    total_rows += n
                    warnings.extend(file_warnings)
        except Exception as exc:
            msg = f"Bronze ingestion failed; transaction rolled back: {exc}"
            logger.error(msg)
            errors.append(msg)

        return StageResult(
            success=len(errors) == 0,
            rows_written=total_rows,
            errors=errors,
            warnings=warnings,
        )

    def _ingest_zip(self, conn, zip_path: str, country: str, community: str) -> tuple[int, list[dict]]:
        """Extract SQLite from zip and load all tables into bronze_havi. Returns total rows."""
        last_modified = datetime.fromtimestamp(os.path.getmtime(zip_path), tz=timezone.utc)

        run_id = str(uuid.uuid4())
        extracted_at = datetime.now(timezone.utc)
        total_rows = 0
        warnings: list[dict] = []

        tables = _read_sqlite_from_zip(zip_path)

        for table_name, df in tables.items():
            if df.empty:
                continue
            if table_name not in FORM_COLUMNS:
                warning = dict(
                    check='unsupported_table',
                    severity='WARNING',
                    country=country,
                    site=None,
                    field=table_name,
                    record_count=len(df),
                    detail=(
                        f"Unsupported table {table_name} found in "
                        f"{os.path.basename(zip_path)}; table was not loaded."
                    ),
                    affected_subjids=None,
                    affected_tablets=os.path.basename(zip_path),
                )
                warnings.append(warning)
                logger.warning("[%s] %s", country, warning['detail'])
                continue

            # Restrict to declared form columns — extra device columns are ignored,
            # missing columns will be NULL in bronze.
            declared = FORM_COLUMNS.get(table_name, [])
            source_columns = set(df.columns)
            declared_columns = set(declared)
            extra_columns = sorted(source_columns - declared_columns)
            missing_columns = sorted(declared_columns - source_columns)
            if extra_columns or missing_columns:
                warnings.append(dict(
                    check='schema_drift',
                    severity='WARNING',
                    country=country,
                    site=None,
                    field=table_name,
                    record_count=len(df),
                    detail=(
                        f"Schema drift in {os.path.basename(zip_path)}:{table_name}; "
                        f"extra_columns={extra_columns}; missing_columns={missing_columns}"
                    ),
                    affected_subjids=None,
                    affected_tablets=os.path.basename(zip_path),
                ))
                logger.warning(
                    "[%s] Schema drift in %s/%s: extra=%s missing=%s",
                    country, os.path.basename(zip_path), table_name,
                    extra_columns, missing_columns,
                )
            df = df[[c for c in declared if c in df.columns]].copy()

            df['run_uuid'] = run_id
            df['file_name'] = os.path.basename(zip_path)
            df['file_path'] = zip_path
            df['country'] = country
            df['community'] = community
            df['extracted_at'] = extracted_at

            df.to_sql(
                table_name, conn,
                schema='bronze_havi',
                if_exists='append',
                index=False,
            )
            total_rows += len(df)
            logger.info(
                f"Ingested {len(df)} rows from '{os.path.basename(zip_path)}'"
                f" → bronze_havi.{table_name}"
            )

        meta = pd.DataFrame([{
            'run_uuid': run_id,
            'file_name': os.path.basename(zip_path),
            'file_path': zip_path,
            'country': country,
            'community': community,
            'extracted_at': extracted_at,
            'last_modified': last_modified,
            'loaded': True,
        }])
        meta.to_sql('meta', conn, schema='bronze_havi', if_exists='append', index=False)
        conn.execute(text(
            'CREATE INDEX IF NOT EXISTS idx_meta_fp_lm '
            'ON bronze_havi.meta (file_path, last_modified)'
        ))

        return total_rows, warnings
