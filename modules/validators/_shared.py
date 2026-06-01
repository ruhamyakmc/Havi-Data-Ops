from __future__ import annotations

import re

import pandas as pd

_DEFAULT_VALID_MRC_CODES: frozenset[int] = frozenset(
    {12, 23, 25, 29, 31, 36, 37, 40, 42, 47, 56, 59, 62, 64, 66, 69, 70}
)
_BARCODE_RE = re.compile(r'^H26-[A-Z0-9]+-\d{4}$')

_CLOCATION_MAP = {1: 'outdoor', 2: 'indoor'}

_REPORT_COLS = [
    'check', 'severity', 'mrccode', 'field',
    'record_count', 'detail', 'clocation', 'hhid', 'session_id',
]

_COLLECTION_REQUIRED = [
    'uniqueid', 'session_id', 'mrccode', 'hhid',
    'dateofcollection', 'starttime', 'stoptime',
]
_MOSQUITO_REQUIRED = [
    'uniqueid', 'session_id', 'mosqnum', 'chour',
    'grossspecies', 'mosq_barcode', 'starttime', 'stoptime',
]
_ASSAY_REQUIRED = [
    'uniqueid', 'site_id', 'assaynum', 'mosqspecies',
    'numtested', 'numdead', 'numkd',
]

_OBS_COLUMNS = [
    'obs_4_5pm', 'obs_5_6pm', 'obs_6_7pm', 'obs_7_8pm', 'obs_8_9pm',
    'obs_9_10pm', 'obs_10_11pm', 'obs_11pm_12am', 'obs_12_1am', 'obs_1_2am',
    'obs_2_3am', 'obs_3_4am', 'obs_4_5am', 'obs_5_6am', 'obs_6_7am',
    'obs_7_8am', 'obs_8_9am', 'obs_9_10am',
]
_LATE_NIGHT_OBS = [
    'obs_9_10pm', 'obs_10_11pm', 'obs_11pm_12am', 'obs_12_1am',
    'obs_1_2am', 'obs_2_3am', 'obs_3_4am', 'obs_4_5am', 'obs_5_6am',
]
_HBO_HOUSEHOLD_REQUIRED = ['uniqueid', 'session_id', 'mrccode', 'hhid', 'dateofobservation']
_HBO_PERSON_REQUIRED = ['uniqueid', 'session_id', 'individualnum']


def _clocation(df: pd.DataFrame, mask) -> str:
    """Return human-readable clocation label(s) for rows matching mask."""
    if 'clocation' not in df.columns:
        return ''
    try:
        vals = pd.to_numeric(df.loc[mask, 'clocation'], errors='coerce').dropna().astype(int).unique()
        labels = sorted({_CLOCATION_MAP.get(v, str(v)) for v in vals})
        return ' & '.join(labels)
    except Exception:
        return ''


def _issue(
    check: str,
    severity: str,
    field: str,
    count: int,
    detail: str,
    clocation: str = '',
    mrccode: str = '',
    hhid: str = '',
    session_id: str = '',
) -> dict:
    return {
        'check': check,
        'severity': severity,
        'mrccode': mrccode,
        'field': field,
        'record_count': count,
        'detail': detail,
        'clocation': clocation,
        'hhid': hhid,
        'session_id': session_id,
    }
