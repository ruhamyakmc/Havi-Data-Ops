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
| 1 | `FtpToExtracted` | Downloads latest `havi_entomology_*.zip` archive per device into `Extracted/{country}/` and validates ZIP integrity. |
| 2 | `SqliteToBronze` | Reads SQLite tables from each ZIP and appends raw text data plus ETL metadata into `bronze_havi`. |
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
