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
        'aspirations_method',
        'rain',
        'windforce',
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
        'clocation',
        'mrccode',
        'sitecode',
        'mosqnum',
        'chour',
        'grossspecies',
        'abdstatus',
        'mosq_barcode_num',
        'mosq_barcode_num2',
        'mosq_barcode',
        'aspirations_method',
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
    'run_uuid',
    'file_name',
    'file_path',
    'country',
    'community',
    'extracted_at',
]

# Default values applied in silver for columns absent in older app versions.
# NULL in bronze means the device didn't collect the field; -6 = Not applicable.
COLUMN_DEFAULTS: dict[str, dict[str, object]] = {
    'ento_collection': {
        'aspirations_method': '-6',
        'rain': '-6',
        'windforce': '-6',
    },
    'ento_mosquito': {
        'aspirations_method': '-6',
    },
}

PRIMARY_KEYS: dict[str, list[str]] = {
    'ento_collection': ['uniqueid', 'clocation'],
}

DEFAULT_PRIMARY_KEY = ['uniqueid']

# Logical dedup keys: when the same real-world record appears in multiple
# archives (re-sync or genuine edit), collapse to the latest lastmod.
LOGICAL_DEDUP_KEYS: dict[str, list[str]] = {
    'ento_collection': ['session_id', 'clocation', 'datasource'],
    'ento_mosquito': ['mosq_barcode'],
    'hbo_household': ['session_id'],
    'hbo_person': ['session_id', 'individualnum'],
}

COLUMN_TYPES: dict[str, str] = {
    'extracted_at': 'TIMESTAMPTZ',
    'collection_date': 'DATE',
    'observation_date': 'DATE',
    'assay_date': 'DATE',
    'total_mosquito_count': 'INTEGER',
    'mosquito_number': 'INTEGER',
    'assay_count': 'INTEGER',
    'num_tested': 'INTEGER',
    'num_dead': 'INTEGER',
    'num_knockdown': 'INTEGER',
    'pct_mortality_value': 'DOUBLE PRECISION',
    'pct_knockdown_value': 'DOUBLE PRECISION',
    'sleeping_rooms_count': 'INTEGER',
    'sleeping_areas_count': 'INTEGER',
    'hanging_bednets_count': 'INTEGER',
    'people_count': 'INTEGER',
    'individual_number': 'INTEGER',
    'age_years': 'DOUBLE PRECISION',
}

GOLD_DERIVED_COLUMNS: dict[str, list[str]] = {
    'ento_collection': ['collection_date', 'total_mosquito_count'],
    'ento_mosquito': ['collection_date', 'mosquito_number'],
    'pheno_site': ['assay_date', 'assay_count'],
    'pheno_assay': [
        'assay_date',
        'num_tested',
        'num_dead',
        'num_knockdown',
        'pct_mortality_value',
        'pct_knockdown_value',
    ],
    'hbo_household': [
        'observation_date',
        'sleeping_rooms_count',
        'sleeping_areas_count',
        'hanging_bednets_count',
        'people_count',
    ],
    'hbo_person': ['observation_date', 'individual_number', 'age_years'],
}

INDEX_COLUMNS: dict[str, list[list[str]]] = {
    'ento_collection': [
        ['uniqueid', 'clocation'],
        ['session_id'],
        ['mrccode'],
        ['hhid'],
        ['run_uuid'],
    ],
    'ento_mosquito': [
        ['uniqueid'],
        ['session_id', 'clocation'],
        ['session_id'],
        ['mosq_barcode'],
        ['run_uuid'],
    ],
    'pheno_site': [
        ['site_id'],
        ['uniqueid'],
        ['run_uuid'],
    ],
    'pheno_assay': [
        ['site_id'],
        ['uniqueid'],
        ['run_uuid'],
    ],
    'hbo_household': [
        ['session_id'],
        ['hhid'],
        ['uniqueid'],
        ['run_uuid'],
    ],
    'hbo_person': [
        ['session_id'],
        ['uniqueid'],
        ['run_uuid'],
    ],
}


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def column_type(column: str) -> str:
    return COLUMN_TYPES.get(column, 'TEXT')


def column_definitions(columns: list[str]) -> str:
    return ', '.join(
        f'{_quote_identifier(col)} {column_type(col)}'
        for col in columns
    )


def ensure_empty_table(conn, schema: str, table: str, columns: list[str]) -> None:
    quoted_columns = column_definitions(columns)
    conn.execute(text(
        f'CREATE TABLE IF NOT EXISTS {_quote_identifier(schema)}.{_quote_identifier(table)} '
        f'({quoted_columns})'
    ))
    for column in columns:
        conn.execute(text(
            f'ALTER TABLE {_quote_identifier(schema)}.{_quote_identifier(table)} '
            f'ADD COLUMN IF NOT EXISTS {_quote_identifier(column)} {column_type(column)}'
        ))


def bronze_columns(table: str) -> list[str]:
    return FORM_COLUMNS[table] + BRONZE_METADATA_COLUMNS


def silver_columns(table: str) -> list[str]:
    return FORM_COLUMNS[table] + SILVER_METADATA_COLUMNS


def gold_columns(table: str) -> list[str]:
    return silver_columns(table) + GOLD_DERIVED_COLUMNS.get(table, [])


def primary_key_columns(table: str) -> list[str]:
    return PRIMARY_KEYS.get(table, DEFAULT_PRIMARY_KEY)


def logical_dedup_columns(table: str) -> list[str]:
    return LOGICAL_DEDUP_KEYS.get(table, [])


def column_defaults(table: str) -> dict[str, object]:
    return COLUMN_DEFAULTS.get(table, {})
