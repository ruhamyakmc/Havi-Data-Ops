from __future__ import annotations

import io
import logging
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from stages.base import BaseStage, StageResult

logger = logging.getLogger(__name__)

BOX_CONFIG_PATH = Path('secrets/box_config.json')


def _get_box_client():
    if not BOX_CONFIG_PATH.exists():
        logger.warning(
            "Box credentials not found at '%s' — upload will be skipped.",
            BOX_CONFIG_PATH,
        )
        return None
    try:
        from boxsdk import JWTAuth, Client
        auth = JWTAuth.from_settings_file(str(BOX_CONFIG_PATH))
        return Client(auth)
    except Exception as exc:
        logger.error("Failed to build Box client: %s", exc)
        return None


def _first_n_sessions(df: pd.DataFrame, date_col: str, n: int) -> pd.Series:
    """Return a boolean mask for rows belonging to the first n distinct nights per hhid."""
    dates = pd.to_datetime(df[date_col], errors='coerce').dt.date
    ranked = (
        df.assign(_date=dates)
        .groupby('hhid')['_date']
        .transform(lambda s: s.rank(method='dense'))
    )
    return ranked <= n


class ExportFirst3(BaseStage):
    name = 'export_first3'
    dependencies: list[str] = []

    def run(self) -> StageResult:
        n = int((self.config.get('export') or {}).get('n_collections', 3))
        errors: list[str] = []
        csv_buffers: dict[str, io.StringIO] = {}
        total_rows = 0

        # ── Load silver tables ────────────────────────────────────────────
        def read_silver(table: str) -> pd.DataFrame:
            try:
                return pd.read_sql(f'SELECT * FROM silver_havi."{table}"', self.engine)
            except Exception as exc:
                logger.warning("Could not read silver_havi.%s: %s", table, exc)
                return pd.DataFrame()

        collection_df = read_silver('ento_collection')
        mosquito_df = read_silver('ento_mosquito')
        household_df = read_silver('hbo_household')
        person_df = read_silver('hbo_person')

        # ── HLC: first n nights per household ────────────────────────────
        if not collection_df.empty and 'hhid' in collection_df.columns:
            try:
                mask = _first_n_sessions(collection_df, 'starttime', n)
                hlc_collection = collection_df[mask].copy()

                # Split by datasource and export collection + mosquito per datasource
                if 'datasource' in hlc_collection.columns:
                    datasources = sorted(hlc_collection['datasource'].dropna().unique())
                else:
                    hlc_collection['datasource'] = ''
                    datasources = ['']

                for ds in datasources:
                    ds_label = str(ds) if ds != '' else 'all'
                    suffix = f'_ds{ds_label}' if ds_label != 'all' else ''

                    if ds != '':
                        ds_collection = hlc_collection[hlc_collection['datasource'].astype(str) == str(ds)]
                    else:
                        ds_collection = hlc_collection

                    # Collection CSV
                    col_name = f'hlc_collection{suffix}.csv'
                    buf = io.StringIO()
                    ds_collection.to_csv(buf, index=False)
                    csv_buffers[col_name] = buf
                    total_rows += len(ds_collection)
                    logger.info(
                        "HLC collection (datasource=%s): %d row(s) → %s",
                        ds_label, len(ds_collection), col_name,
                    )

                    # Mosquito CSV — join via session_id
                    if not mosquito_df.empty and 'session_id' in mosquito_df.columns:
                        ds_sessions = set(ds_collection['session_id'].dropna().astype(str))
                        ds_mosquito = mosquito_df[
                            mosquito_df['session_id'].astype(str).isin(ds_sessions)
                        ]
                        mosq_name = f'hlc_mosquito{suffix}.csv'
                        buf = io.StringIO()
                        ds_mosquito.to_csv(buf, index=False)
                        csv_buffers[mosq_name] = buf
                        total_rows += len(ds_mosquito)
                        logger.info(
                            "HLC mosquito (datasource=%s): %d row(s) → %s",
                            ds_label, len(ds_mosquito), mosq_name,
                        )

            except Exception as exc:
                msg = f"HLC export failed: {exc}"
                logger.error(msg)
                errors.append(msg)
        else:
            logger.warning("ento_collection is empty or missing hhid — skipping HLC export.")

        # ── HBO: first n nights per household ────────────────────────────
        if not household_df.empty and 'hhid' in household_df.columns:
            try:
                mask = _first_n_sessions(household_df, 'dateofobservation', n)
                hbo_household = household_df[mask].copy()
                hbo_sessions = set(hbo_household['session_id'].dropna().astype(str))

                # Household CSV
                buf = io.StringIO()
                hbo_household.to_csv(buf, index=False)
                csv_buffers['hbo_household.csv'] = buf
                total_rows += len(hbo_household)
                logger.info("HBO household: %d row(s).", len(hbo_household))

                # Person CSV — filter by session_id
                if not person_df.empty and 'session_id' in person_df.columns:
                    hbo_person = person_df[
                        person_df['session_id'].astype(str).isin(hbo_sessions)
                    ]
                    buf = io.StringIO()
                    hbo_person.to_csv(buf, index=False)
                    csv_buffers['hbo_person.csv'] = buf
                    total_rows += len(hbo_person)
                    logger.info("HBO person: %d row(s).", len(hbo_person))

            except Exception as exc:
                msg = f"HBO export failed: {exc}"
                logger.error(msg)
                errors.append(msg)
        else:
            logger.warning("hbo_household is empty or missing hhid — skipping HBO export.")

        if not csv_buffers:
            logger.warning("Nothing to export.")
            return StageResult(success=len(errors) == 0, rows_written=0, errors=errors)

        # ── Build zip ─────────────────────────────────────────────────────
        today = date.today().isoformat()
        zip_name = f'havi_first{n}_export_{today}.zip'
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for name, buf in csv_buffers.items():
                zf.writestr(name, buf.getvalue())

        zip_size_kb = round(zip_buffer.tell() / 1024, 1)
        logger.info(
            "Created '%s' with %d file(s) (%.1f KB).",
            zip_name, len(csv_buffers), zip_size_kb,
        )

        if errors:
            return StageResult(success=False, rows_written=total_rows, errors=errors)

        # ── Upload to Box ─────────────────────────────────────────────────
        folder_id = (self.config.get('box') or {}).get('folder_id')

        if not folder_id:
            logger.warning("config.json missing 'box.folder_id' — zip built but NOT uploaded.")
            return StageResult(success=True, rows_written=total_rows)

        client = _get_box_client()
        if client is None:
            return StageResult(success=True, rows_written=total_rows)

        try:
            zip_buffer.seek(0)
            uploaded = client.folder(folder_id).upload_stream(zip_buffer, zip_name)
            logger.info(
                "Uploaded '%s' to Box folder %s (file ID: %s).",
                zip_name, folder_id, uploaded.id,
            )
        except Exception as exc:
            msg = f"Box upload failed: {exc}"
            logger.error(msg)
            errors.append(msg)

        return StageResult(
            success=len(errors) == 0,
            rows_written=total_rows,
            errors=errors,
        )
