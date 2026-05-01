from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, URL

from modules.havi_schema import FORM_COLUMNS, INDEX_COLUMNS, primary_key_columns

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


def create_table_indexes(conn, schema: str, table: str) -> None:
    """Create standard uniqueness and lookup indexes for a modeled HAVI table."""
    if table not in FORM_COLUMNS:
        return

    key_columns = primary_key_columns(table)
    suffix = '_'.join(key_columns)
    unique_index_name = f'uidx_{table}_{suffix}'
    quoted_key_columns = ', '.join(quote_identifier(col) for col in key_columns)
    not_null_filter = ' AND '.join(
        f'{quote_identifier(col)} IS NOT NULL' for col in key_columns
    )
    conn.execute(text(
        f'CREATE UNIQUE INDEX IF NOT EXISTS {quote_identifier(unique_index_name)} '
        f'ON {quote_identifier(schema)}.{quote_identifier(table)} ({quoted_key_columns}) '
        f'WHERE {not_null_filter}'
    ))

    for columns in INDEX_COLUMNS.get(table, []):
        if columns == key_columns:
            continue
        suffix = '_'.join(columns)
        index_name = f'idx_{table}_{suffix}'
        quoted_columns = ', '.join(quote_identifier(col) for col in columns)
        conn.execute(text(
            f'CREATE INDEX IF NOT EXISTS {quote_identifier(index_name)} '
            f'ON {quote_identifier(schema)}.{quote_identifier(table)} ({quoted_columns})'
        ))


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


def log_pipeline_row_counts(
    engine: Engine,
    run_id: str,
    tables: list[str] | None = None,
) -> None:
    """Persist per-layer row counts and warn on count mismatches.

    This is intentionally non-fatal: row-count audit failures should be visible,
    but should not hide the ETL result or notification path.
    """
    tables = tables or sorted(FORM_COLUMNS)
    counted_at = datetime.now(timezone.utc)
    rows: list[dict] = []

    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS havi.pipeline_row_counts (
                    run_id     TEXT        NOT NULL,
                    counted_at TIMESTAMPTZ NOT NULL,
                    layer      TEXT        NOT NULL,
                    table_name TEXT        NOT NULL,
                    row_count  INTEGER     NOT NULL
                )
            """))

            for schema in SCHEMAS:
                for table in tables:
                    exists = conn.execute(
                        text("""
                            SELECT EXISTS (
                                SELECT 1
                                FROM information_schema.tables
                                WHERE table_schema = :schema
                                  AND table_name = :table
                                  AND table_type = 'BASE TABLE'
                            )
                        """),
                        {'schema': schema, 'table': table},
                    ).scalar()
                    if not exists:
                        continue

                    row_count = conn.execute(text(
                        f'SELECT COUNT(*) FROM {quote_identifier(schema)}.{quote_identifier(table)}'
                    )).scalar_one()
                    rows.append({
                        'run_id': run_id,
                        'counted_at': counted_at,
                        'layer': schema,
                        'table_name': table,
                        'row_count': int(row_count),
                    })

            if rows:
                conn.execute(
                    text("""
                        INSERT INTO havi.pipeline_row_counts
                            (run_id, counted_at, layer, table_name, row_count)
                        VALUES
                            (:run_id, :counted_at, :layer, :table_name, :row_count)
                    """),
                    rows,
                )

        _log_count_mismatches(rows)
        logger.info('Pipeline row counts logged for run %s (%d row(s)).', run_id, len(rows))
    except Exception as exc:
        logger.error('Failed to write pipeline_row_counts: %s', exc)


def _log_count_mismatches(rows: list[dict]) -> None:
    by_table: dict[str, dict[str, int]] = {}
    for row in rows:
        by_table.setdefault(row['table_name'], {})[row['layer']] = row['row_count']

    comparable_layers = ['silver_havi', 'gold_havi', 'havi']
    for table, counts in sorted(by_table.items()):
        comparable = {
            layer: counts[layer]
            for layer in comparable_layers
            if layer in counts
        }
        if len(comparable) >= 2 and len(set(comparable.values())) > 1:
            logger.warning(
                'Layer row-count mismatch for %s: %s',
                table,
                ', '.join(f'{layer}={count}' for layer, count in comparable.items()),
            )
