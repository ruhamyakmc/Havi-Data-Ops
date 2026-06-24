from __future__ import annotations

import logging
import re

from sqlalchemy import text

from modules.db import create_table_indexes, quote_identifier
from modules.havi_schema import FORM_COLUMNS, column_definitions, gold_columns
from stages.base import BaseStage, StageResult

logger = logging.getLogger(__name__)


def _validate_table_name(name: str) -> str:
    """Reject names that could break SQL identifier quoting."""
    if not re.match(r'^[a-z_][a-z0-9_]*$', name):
        raise ValueError(f"Invalid table name: '{name}'")
    return name


class PromoteHavi(BaseStage):
    name = 'promote_havi'
    dependencies: list[str] = ['measures_havi']

    def run(self) -> StageResult:
        errors: list[str] = []

        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'gold_havi' AND table_type = 'BASE TABLE'"
                )
            ).fetchall()

            tables = [r[0] for r in rows]
            logger.info(f"Promoting {len(tables)} table(s) from gold_havi → havi.")

            for table in tables:
                _validate_table_name(table)
                try:
                    if table in FORM_COLUMNS:
                        columns = gold_columns(table)
                        target_exists = conn.execute(text("""
                            SELECT EXISTS (
                                SELECT 1 FROM information_schema.tables
                                WHERE table_schema = 'havi'
                                  AND table_name = :table
                                  AND table_type = 'BASE TABLE'
                            )
                        """), {'table': table}).scalar()
                        quoted_columns = ', '.join(quote_identifier(col) for col in columns)
                        source_columns = ', '.join(
                            f'{quote_identifier(col)}' for col in columns
                        )
                        if not target_exists:
                            conn.execute(text(
                                f'CREATE TABLE havi.{quote_identifier(table)} '
                                f'({column_definitions(columns)})'
                            ))
                        conn.execute(text(f'TRUNCATE TABLE havi.{quote_identifier(table)}'))
                        conn.execute(text(
                            f'INSERT INTO havi.{quote_identifier(table)} ({quoted_columns}) '
                            f'SELECT {source_columns} FROM gold_havi.{quote_identifier(table)}'
                        ))
                    else:
                        target_exists = conn.execute(text("""
                            SELECT EXISTS (
                                SELECT 1 FROM information_schema.tables
                                WHERE table_schema = 'havi'
                                  AND table_name = :table
                                  AND table_type = 'BASE TABLE'
                            )
                        """), {'table': table}).scalar()
                        if target_exists:
                            conn.execute(text(f'TRUNCATE TABLE havi.{quote_identifier(table)}'))
                            conn.execute(text(
                                f'INSERT INTO havi.{quote_identifier(table)} '
                                f'SELECT * FROM gold_havi.{quote_identifier(table)}'
                            ))
                        else:
                            conn.execute(text(
                                f'CREATE TABLE havi.{quote_identifier(table)} AS '
                                f'SELECT * FROM gold_havi.{quote_identifier(table)}'
                            ))
                    create_table_indexes(conn, 'havi', table)

                    logger.info(f"  Promoted: gold_havi.{table} → havi.{table}")
                except Exception as exc:
                    msg = f"Failed to promote '{table}': {exc}"
                    logger.error(msg)
                    errors.append(msg)
                    raise

        return StageResult(
            success=len(errors) == 0,
            rows_written=len(tables),
            errors=errors,
        )
