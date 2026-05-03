from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / 'migrations'


def _load_migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(directory.glob('*.sql'))


def run_migrations(engine: Engine, directory: Path = MIGRATIONS_DIR) -> None:
    """Apply SQL migrations once, tracking applied filenames in havi.schema_migrations."""
    files = _load_migration_files(directory)
    if not files:
        logger.info('No migrations found in %s.', directory)
        return

    with engine.begin() as conn:
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS havi'))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS havi.schema_migrations (
                filename   TEXT        PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        applied = {
            row[0]
            for row in conn.execute(
                text('SELECT filename FROM havi.schema_migrations')
            ).fetchall()
        }

        for path in files:
            if path.name in applied:
                logger.debug('Migration already applied: %s', path.name)
                continue
            sql = path.read_text().strip()
            if not sql:
                logger.info('Skipping empty migration: %s', path.name)
                continue
            conn.execute(text(sql))
            conn.execute(
                text('INSERT INTO havi.schema_migrations (filename) VALUES (:filename)'),
                {'filename': path.name},
            )
            logger.info('Applied migration: %s', path.name)
