from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import text

from modules.db import create_table_indexes, has_table
from modules.havi_schema import FORM_COLUMNS, ensure_empty_table, silver_columns
from stages.base import BaseStage, StageResult

logger = logging.getLogger(__name__)

SQL_TRANSFORM_DIR = os.path.join(os.path.dirname(__file__), '..', 'sql', 'transform')


def _load_sql_files(directory: str) -> list[Path]:
    """Return all .sql files in *directory*, sorted by filename."""
    return sorted(Path(directory).glob('*.sql'))


class TransformHavi(BaseStage):
    name = 'transform_havi'
    dependencies: list[str] = ['bronze_to_silver']

    def run(self) -> StageResult:
        sql_files = _load_sql_files(SQL_TRANSFORM_DIR)
        if not sql_files:
            msg = f"No SQL files found in '{SQL_TRANSFORM_DIR}'."
            logger.error(msg)
            return StageResult(success=False, rows_written=0, errors=[msg])

        errors: list[str] = []

        with self.engine.begin() as conn:
            for sql_path in sql_files:
                source_table = sql_path.stem
                if (
                    source_table in FORM_COLUMNS
                    and not has_table(self.engine, source_table, schema='silver_havi')
                ):
                    ensure_empty_table(
                        conn,
                        schema='silver_havi',
                        table=source_table,
                        columns=silver_columns(source_table),
                    )
                    logger.info(
                        f"Created empty silver_havi.{source_table} for {sql_path.name}."
                    )
                sql = sql_path.read_text()
                try:
                    conn.execute(text(sql))
                    create_table_indexes(conn, 'gold_havi', source_table)
                    logger.info(f"Executed: {sql_path.name}")
                except Exception as exc:
                    msg = f"SQL error in '{sql_path.name}': {exc}"
                    logger.error(msg)
                    errors.append(msg)
                    raise  # roll back the transaction

        return StageResult(
            success=len(errors) == 0,
            rows_written=0,
            errors=errors,
        )
