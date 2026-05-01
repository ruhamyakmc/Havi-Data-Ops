from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, URL

logger = logging.getLogger(__name__)

SCHEMAS = ['bronze_havi', 'silver_havi', 'gold_havi', 'havi']


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def create_db_engine(config) -> Engine:
    """Create a SQLAlchemy engine from the 'db' config block.
    Uses URL.create() to safely handle special characters in the password.
    """
    db = config.get('db')
    with open(db['password_secret_file']) as f:
        password = f.read().strip()
    url = URL.create(
        drivername='postgresql+psycopg2',
        username=db['user'],
        password=password,
        host=db['host'],
        port=db['port'],
        database=db['name'],
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "options": "-c statement_timeout=300000 -c lock_timeout=30000"
        },
    )


def init_schemas(engine: Engine) -> None:
    """Create all medallion schemas if they do not already exist."""
    with engine.connect() as conn:
        for schema in SCHEMAS:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS {quote_identifier(schema)}'))
            logger.debug('Schema ready: %s', schema)
        conn.commit()
    logger.info('Initialised schemas: %s', SCHEMAS)


def has_table(engine: Engine, table: str, schema: str) -> bool:
    """Return whether a table exists in a schema."""
    return inspect(engine).has_table(table, schema=schema)


def log_pipeline_run(
    engine: Engine,
    run_id: str,
    started_at: datetime,
    stage_results: dict,
    stages: list[str],
) -> None:
    """Write one row per stage to havi.pipeline_run_log for auditability.

    Creates the table on first use. Failures here are logged but never
    allowed to propagate — audit logging must not mask ETL results.
    """
    finished_at = datetime.now(timezone.utc)
    rows = []
    for name in stages:
        result = stage_results.get(name)
        if result is None:
            rows.append((run_id, started_at, finished_at, name, False, 0, 'skipped'))
        else:
            error_text = '; '.join(result.errors) if result.errors else None
            rows.append((
                run_id, started_at, finished_at,
                name, result.success, result.rows_written, error_text,
            ))

    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS havi.pipeline_run_log (
                    run_id       TEXT        NOT NULL,
                    started_at   TIMESTAMPTZ NOT NULL,
                    finished_at  TIMESTAMPTZ NOT NULL,
                    stage        TEXT        NOT NULL,
                    success      BOOLEAN     NOT NULL,
                    rows_written INTEGER     NOT NULL DEFAULT 0,
                    error_text   TEXT
                )
            """))
            conn.execute(
                text("""
                    INSERT INTO havi.pipeline_run_log
                        (run_id, started_at, finished_at, stage, success, rows_written, error_text)
                    VALUES
                        (:run_id, :started_at, :finished_at, :stage, :success, :rows_written, :error_text)
                """),
                [
                    {
                        'run_id': run_id,
                        'started_at': started_at,
                        'finished_at': finished_at,
                        'stage': stage,
                        'success': success,
                        'rows_written': rows_written,
                        'error_text': error_text,
                    }
                    for run_id, started_at, finished_at, stage, success, rows_written, error_text
                    in rows
                ],
            )
        logger.info('Pipeline run %s logged (%d stage(s)).', run_id, len(rows))
    except Exception as exc:
        logger.error('Failed to write pipeline_run_log: %s', exc)
