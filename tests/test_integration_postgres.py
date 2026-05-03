from __future__ import annotations

import os
import sqlite3
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from modules.db import SCHEMAS, init_schemas
from stages.bronze_to_silver import BronzeToSilver
from stages.measures_havi import MeasuresHavi
from stages.promote_havi import PromoteHavi
from stages.sqlite_to_bronze import SqliteToBronze
from stages.transform_havi import TransformHavi


class _Config:
    def __init__(self, data: dict):
        self.data = data

    def get(self, key: str, default=None):
        return self.data.get(key, default)


def _write_fixture_sqlite(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("""
            CREATE TABLE ento_collection (
                session_id TEXT,
                dateofcollection TEXT,
                clocation TEXT,
                mrccode TEXT,
                hhid TEXT,
                datasource TEXT,
                numfanoph TEXT,
                nummanoph TEXT,
                numculex TEXT,
                uniqueid TEXT,
                swver TEXT,
                survey_id TEXT,
                starttime TEXT,
                stoptime TEXT,
                lastmod TEXT
            )
        """)
        conn.execute("""
            INSERT INTO ento_collection VALUES (
                's1', '2026-04-20', 'indoor', '12', 'hh1', 'tablet',
                '1', '0', '0', 'u1', '1.0', 'survey-1',
                '2026-04-20T18:00:00Z', '2026-04-20T19:00:00Z',
                '2026-04-20T19:05:00Z'
            )
        """)
        conn.execute("""
            CREATE TABLE ento_mosquito (
                session_id TEXT,
                hhid TEXT,
                dateofcollection TEXT,
                clocation TEXT,
                mrccode TEXT,
                sitecode TEXT,
                mosqnum TEXT,
                chour TEXT,
                grossspecies TEXT,
                abdstatus TEXT,
                mosq_barcode_num TEXT,
                mosq_barcode_num2 TEXT,
                mosq_barcode TEXT,
                uniqueid TEXT,
                swver TEXT,
                survey_id TEXT,
                starttime TEXT,
                stoptime TEXT,
                lastmod TEXT
            )
        """)
        conn.execute("""
            INSERT INTO ento_mosquito VALUES (
                's1', 'hh1', '2026-04-20', 'indoor', '12', 'site-1', '1', '18',
                'Anopheles', 'fed', '1', '1', 'mb1', 'm1', '1.0',
                'survey-1', '2026-04-20T18:10:00Z',
                '2026-04-20T18:20:00Z', '2026-04-20T18:25:00Z'
            )
        """)
        conn.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_core_etl_runs_end_to_end_against_postgres(tmp_path, monkeypatch):
    database_url = os.getenv('HAVI_TEST_DATABASE_URL')
    if not database_url:
        pytest.skip('Set HAVI_TEST_DATABASE_URL to run the Postgres integration test.')

    extract_dir = tmp_path / 'Extracted'
    extract_dir.mkdir()
    sqlite_path = tmp_path / 'fixture.sqlite'
    _write_fixture_sqlite(sqlite_path)
    zip_path = extract_dir / 'havi_entomology_101_2026-04-20_12_00.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(sqlite_path, arcname='fixture.sqlite')

    monkeypatch.setattr(
        'stages.sqlite_to_bronze.get_country_paths',
        lambda country: {'download_path': str(tmp_path), 'extract_path': str(extract_dir)},
    )

    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            for schema in reversed(SCHEMAS):
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        init_schemas(engine)

        config = _Config({
            'communities': {
                'uganda_test': {
                    'country': 'uganda',
                    'community_name': 'test-community',
                    'remotefilepath_download': '/unused/',
                },
            },
            'trial': {
                'dedup_key': 'uniqueid',
                'dedup_strategy': 'latest_snapshot',
                'valid_mrc_codes': [12],
                'study_start_date': '2020-01-01',
            },
        })

        for stage_cls in (
            SqliteToBronze,
            BronzeToSilver,
            TransformHavi,
            MeasuresHavi,
            PromoteHavi,
        ):
            result = stage_cls(config=config, engine=engine).run()
            assert result.success, result.errors

        with engine.connect() as conn:
            promoted = conn.execute(text("""
                SELECT COUNT(*) AS row_count, MAX(total_mosquito_count) AS total_count
                FROM havi.ento_collection
            """)).one()
            extracted_type = conn.execute(text("""
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'havi'
                  AND table_name = 'ento_collection'
                  AND column_name = 'extracted_at'
            """)).scalar_one()
            total_count_type = conn.execute(text("""
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'havi'
                  AND table_name = 'ento_collection'
                  AND column_name = 'total_mosquito_count'
            """)).scalar_one()

        assert promoted.row_count == 1
        assert promoted.total_count == 1
        assert extracted_type == 'timestamp with time zone'
        assert total_count_type == 'integer'
    finally:
        with engine.begin() as conn:
            for schema in reversed(SCHEMAS):
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
