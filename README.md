# HAVI Entomology ETL

A containerised ETL pipeline for HAVI entomology data. It downloads SQLite ZIP
archives from SFTP, ingests the tablet forms into PostgreSQL, deduplicates records,
runs entomology QC checks, and promotes analysis-ready tables to a stable `havi`
schema.

## Architecture

```
SFTP server -> Extracted/ -> bronze_havi -> silver_havi -> gold_havi -> havi
              (.zip files)    raw text      deduped       transformed   stable
```

| Stage | Class | What it does |
|---|---|---|
| 1 | `FtpToExtracted` | Downloads HAVI ZIP archives into `Extracted/` and validates ZIP integrity. This build is constrained to one configured community because the extract directory is shared. |
| 2 | `SqliteToBronze` | Rebuilds `bronze_havi` atomically from all ZIPs in `Extracted/`, loading raw text data plus ETL metadata. A failed ingest rolls back to the previous bronze state. |
| 3 | `BronzeToSilver` | Drops exact duplicates and deduplicates by `uniqueid`, keeping the newest extraction. |
| 4 | `TransformHavi` | Executes SQL in `sql/transform/` to build `gold_havi` form tables. |
| 5 | `MeasuresHavi` | Runs entomology validation checks and writes `gold_havi.ds_validation_report`; also runs SQL measures. |
| 6 | `PromoteHavi` | Atomically promotes `gold_havi` tables to the stable `havi` schema. |

The CLI entrypoint is `havi.py`. Stage order is derived from declared dependencies.

## Quick Start

Create secrets:

```bash
mkdir -p secrets
echo 'your_db_password' > secrets/db_password.txt
cp /path/to/HAVI.ini secrets/
cp /path/to/HAVI.key secrets/
```

Create config:

```bash
cp config.json.example config.json
```

Run the full pipeline once:

```bash
docker compose run --rm etl python havi.py -a
```

Start the scheduled service:

```bash
docker compose up -d
```

## Running One Stage

```bash
docker compose run --rm etl python havi.py -p <stage_name>
```

Valid stage names: `ftp_to_extracted`, `sqlite_to_bronze`, `bronze_to_silver`,
`transform_havi`, `measures_havi`, `promote_havi`.

Manual utility stages are excluded from `-a` and must be run explicitly with
`-p`: `export_box`, `export_visits`, and `round_status`.

## Configuration

`config.json` must contain:

| Key | Description |
|---|---|
| `ftp` | SFTP hostname and HAVI username. |
| `communities` | Country/community remote path mapping. HAVI normally has one Uganda shared folder. |
| `keyfiles` | Fernet credential files for SFTP. |
| `db` | PostgreSQL connection details and password secret file. |
| `trial` | Trial name and `dedup_key`. |
| `schedule` | `pipeline_cron` in UTC. |
| `email` | Optional SMTP settings for pipeline and field data-quality notifications. |

This deployment currently supports exactly one configured community. The code
uses a shared `Extracted/` directory, so multiple communities are rejected at
startup unless `get_country_paths()` is changed to return isolated paths.

## Operational Notes

`sqlite_to_bronze` is a full rebuild stage: each successful run truncates and
reloads bronze tables inside one PostgreSQL transaction. Rerunning the stage
with the same ZIP files produces the same bronze rows, and a failure leaves the
previous committed bronze layer in place.

`measures_havi` publishes the validation report and SQL measure tables in one
transaction. If a measure SQL file fails, the previous measures output remains
available.

`promote_havi` preserves existing `havi` table objects where possible by
truncating and inserting from `gold_havi`, instead of dropping with `CASCADE`.
This keeps dependent views and grants attached when schemas are compatible.

Box export stages save local output first. If `box.folder_id` is configured but
Box credentials are missing or invalid, the stage fails so scheduled delivery
problems are visible. If no `box.folder_id` is configured, the local-only export
is treated as successful.

## Database

Docker Compose exposes PostgreSQL on local port `5434`.

| Field | Value |
|---|---|
| Host | `localhost` |
| Port | `5434` |
| Database | `havi` |
| Username | `havi_user` |

pgAdmin is available on `http://localhost:5051` when the `pgadmin` service is running.

## Project Layout

```
.
├── havi.py
├── modules/
│   ├── config.py
│   ├── data_cleaner.py
│   ├── data_validator.py
│   ├── db.py
│   ├── notifier.py
│   ├── sftp_client.py
│   ├── sqlite_reader.py
│   └── utils.py
├── stages/
│   ├── ftp_to_extracted.py
│   ├── sqlite_to_bronze.py
│   ├── bronze_to_silver.py
│   ├── transform_havi.py
│   ├── measures_havi.py
│   └── promote_havi.py
├── sql/
│   ├── transform/
│   └── measures/
└── tests/
```

## Development

```bash
pytest -q
```
