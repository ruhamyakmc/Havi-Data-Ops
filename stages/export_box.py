from __future__ import annotations

import io
import logging
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from stages.base import BaseStage, StageResult

logger = logging.getLogger(__name__)

GOLD_TABLES = [
    'ento_collection',
    'ento_mosquito',
    'hbo_household',
    'hbo_person',
    'pheno_assay',
    'pheno_site',
]

BOX_CONFIG_PATH = Path('secrets/box_config.json')


def _get_box_client():
    """Return a Box JWT service-account client, or None if credentials are absent."""
    if not BOX_CONFIG_PATH.exists():
        logger.warning(
            "Box credentials not found at '%s' — upload will be skipped. "
            "Download the config JSON from the Box developer console and place it there.",
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


class ExportBox(BaseStage):
    name = 'export_box'
    dependencies: list[str] = []

    def run(self) -> StageResult:
        errors: list[str] = []

        # ── 1. Query gold tables ───────────────────────────────────────────
        csv_buffers: dict[str, io.StringIO] = {}
        total_rows = 0

        with self.engine.connect() as conn:
            for table in GOLD_TABLES:
                exists = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'gold_havi'
                          AND table_name   = :table
                          AND table_type   = 'BASE TABLE'
                    )
                """), {'table': table}).scalar()

                if not exists:
                    logger.info("gold_havi.%s does not exist — skipping.", table)
                    continue

                df = pd.read_sql(f'SELECT * FROM gold_havi."{table}"', conn)
                if df.empty:
                    logger.info("gold_havi.%s is empty — skipping.", table)
                    continue

                buf = io.StringIO()
                df.to_csv(buf, index=False)
                csv_buffers[table] = buf
                total_rows += len(df)
                logger.info("Exported gold_havi.%s: %d row(s).", table, len(df))

        if not csv_buffers:
            logger.warning("No non-empty gold tables found — nothing to export.")
            return StageResult(success=True, rows_written=0)

        # ── 2. Build zip ───────────────────────────────────────────────────
        today = date.today().isoformat()
        zip_name = f'havi_export_{today}.zip'
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for table, buf in csv_buffers.items():
                zf.writestr(f'{table}.csv', buf.getvalue())

        zip_size_kb = round(zip_buffer.tell() / 1024, 1)
        logger.info(
            "Created '%s' with %d CSV(s) (%.1f KB).",
            zip_name, len(csv_buffers), zip_size_kb,
        )

        # ── 3. Upload to Box ───────────────────────────────────────────────
        folder_id = (self.config.get('box') or {}).get('folder_id')

        if not folder_id:
            msg = "config.json missing 'box.folder_id' — zip built but NOT uploaded."
            logger.warning(msg)
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
