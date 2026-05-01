from __future__ import annotations

import logging
import re

from sqlalchemy import text

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
                new_table = f'_new_{table}'
                old_table = f'_old_{table}'
                try:
                    # Capture views that depend on havi.{table} BEFORE the rename.
                    # Their definitions reference havi.{table} by name, so after the
                    # swap completes they will correctly point to the new table.
                    dep_views = conn.execute(text("""
                        SELECT
                            n.nspname   AS schema,
                            c.relname   AS viewname,
                            pg_get_viewdef(c.oid, true) AS definition
                        FROM pg_depend d
                        JOIN pg_rewrite r  ON r.oid      = d.objid
                        JOIN pg_class   c  ON c.oid      = r.ev_class
                        JOIN pg_namespace n ON n.oid     = c.relnamespace
                        JOIN pg_class   t  ON t.oid      = d.refobjid
                        JOIN pg_namespace tn ON tn.oid   = t.relnamespace
                        WHERE d.deptype = 'n'
                          AND c.relkind = 'v'
                          AND tn.nspname = 'havi'
                          AND t.relname  = :table
                    """), {"table": table}).fetchall()

                    conn.execute(text(f'DROP TABLE IF EXISTS havi."{new_table}"'))
                    conn.execute(text(
                        f'CREATE TABLE havi."{new_table}" AS '
                        f'SELECT * FROM gold_havi."{table}"'
                    ))
                    conn.execute(text(
                        f'ALTER TABLE IF EXISTS havi."{table}" '
                        f'RENAME TO "{old_table}"'
                    ))
                    conn.execute(text(
                        f'ALTER TABLE havi."{new_table}" RENAME TO "{table}"'
                    ))
                    conn.execute(text(f'DROP TABLE IF EXISTS havi."{old_table}" CASCADE'))

                    # Recreate any views dropped by CASCADE using the pre-rename definitions.
                    for view in dep_views:
                        conn.execute(text(
                            f'CREATE OR REPLACE VIEW {view.schema}."{view.viewname}" AS {view.definition}'
                        ))
                        logger.info(f"  Recreated view: {view.schema}.{view.viewname}")

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
