from __future__ import annotations

from sqlalchemy import text


FORM_COLUMNS: dict[str, list[str]] = {
    'ento_collection': [
        'session_id',
        'dateofcollection',
        'clocation',
        'mrccode',
        'hhid',
        'datasource',
        'numfanoph',
        'nummanoph',
        'numculex',
        'uniqueid',
        'swver',
        'survey_id',
        'starttime',
        'stoptime',
        'lastmod',
    ],
    'ento_mosquito': [
        'session_id',
        'hhid',
        'dateofcollection',
        'mrccode',
        'sitecode',
        'mosqnum',
        'chour',
        'grossspecies',
        'abdstatus',
        'mosq_barcode_num',
        'mosq_barcode_num2',
        'mosq_barcode',
        'uniqueid',
        'swver',
        'survey_id',
        'starttime',
        'stoptime',
        'lastmod',
    ],
    'pheno_site': [
        'site_id',
        'district',
        'subcounty',
        'village',
        'assaydate',
        'nassays',
        'uniqueid',
        'swver',
        'survey_id',
        'starttime',
        'stoptime',
        'lastmod',
    ],
    'pheno_assay': [
        'site_id',
        'assaydate',
        'assaynum',
        'mosqspecies',
        'insecticidename',
        'numtested',
        'numdead',
        'numkd',
        'pctmortality',
        'pctkd',
        'uniqueid',
        'swver',
        'survey_id',
        'starttime',
        'stoptime',
        'lastmod',
    ],
    'hbo_household': [
        'session_id',
        'mrccode',
        'hhid',
        'dateofobservation',
        'numsleeprooms',
        'numsleepareas',
        'numhangbednets',
        'numpeople',
        'uniqueid',
        'swver',
        'survey_id',
        'starttime',
        'stoptime',
        'lastmod',
    ],
    'hbo_person': [
        'session_id',
        'hhid',
        'dateofobservation',
        'individualnum',
        'age',
        'gender',
        'obs_4_5pm',
        'obs_5_6pm',
        'obs_6_7pm',
        'obs_7_8pm',
        'obs_8_9pm',
        'obs_9_10pm',
        'obs_10_11pm',
        'obs_11pm_12am',
        'obs_12_1am',
        'obs_1_2am',
        'obs_2_3am',
        'obs_3_4am',
        'obs_4_5am',
        'obs_5_6am',
        'obs_6_7am',
        'obs_7_8am',
        'obs_8_9am',
        'obs_9_10am',
        'uniqueid',
        'swver',
        'survey_id',
        'starttime',
        'stoptime',
        'lastmod',
    ],
}

BRONZE_METADATA_COLUMNS = [
    'run_uuid',
    'file_name',
    'file_path',
    'country',
    'community',
    'extracted_at',
]

SILVER_METADATA_COLUMNS = [
    'country',
    'community',
]

PRIMARY_KEYS: dict[str, list[str]] = {
    'ento_collection': ['uniqueid', 'clocation'],
}

DEFAULT_PRIMARY_KEY = ['uniqueid']


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def ensure_empty_table(conn, schema: str, table: str, columns: list[str]) -> None:
    quoted_columns = ', '.join(f'{_quote_identifier(col)} TEXT' for col in columns)
    conn.execute(text(
        f'CREATE TABLE IF NOT EXISTS {_quote_identifier(schema)}.{_quote_identifier(table)} '
        f'({quoted_columns})'
    ))


def bronze_columns(table: str) -> list[str]:
    return FORM_COLUMNS[table] + BRONZE_METADATA_COLUMNS


def silver_columns(table: str) -> list[str]:
    return FORM_COLUMNS[table] + SILVER_METADATA_COLUMNS


def primary_key_columns(table: str) -> list[str]:
    return PRIMARY_KEYS.get(table, DEFAULT_PRIMARY_KEY)
