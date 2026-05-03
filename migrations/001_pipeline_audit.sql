CREATE TABLE IF NOT EXISTS havi.pipeline_run_log (
    run_id       TEXT        NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ NOT NULL,
    stage        TEXT        NOT NULL,
    success      BOOLEAN     NOT NULL,
    rows_written INTEGER     NOT NULL DEFAULT 0,
    error_text   TEXT,
    duration_s   DOUBLE PRECISION
);

ALTER TABLE havi.pipeline_run_log
    ADD COLUMN IF NOT EXISTS duration_s DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_pipeline_run_log_run_stage
    ON havi.pipeline_run_log (run_id, stage);

CREATE TABLE IF NOT EXISTS havi.pipeline_row_counts (
    run_id     TEXT        NOT NULL,
    counted_at TIMESTAMPTZ NOT NULL,
    layer      TEXT        NOT NULL,
    table_name TEXT        NOT NULL,
    row_count  INTEGER     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pipeline_row_counts_latest
    ON havi.pipeline_row_counts (layer, table_name, counted_at DESC);
