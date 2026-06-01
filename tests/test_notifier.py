from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from cryptography.fernet import Fernet

from modules.notifier import (
    _build_stage_summary,
    _build_validation_summary,
    _load_smtp_password,
    _query_validation_report,
    send_pipeline_report,
)
from stages.base import StageResult


def test_load_smtp_password_roundtrip(tmp_path):
    key = Fernet.generate_key()
    cipher = Fernet(key)
    key_file = tmp_path / 'smtp.key'
    ini_file = tmp_path / 'smtp.ini'
    key_file.write_text(key.decode())
    ini_file.write_text(f"Password={cipher.encrypt(b's3cr3t').decode()}\n")

    assert _load_smtp_password(str(ini_file), str(key_file)) == 's3cr3t'


def test_load_smtp_password_missing_raises(tmp_path):
    key = Fernet.generate_key()
    key_file = tmp_path / 'smtp.key'
    ini_file = tmp_path / 'smtp.ini'
    key_file.write_text(key.decode())
    ini_file.write_text('Host=smtp.example.com\n')

    with pytest.raises(KeyError, match='Password'):
        _load_smtp_password(str(ini_file), str(key_file))


def test_query_validation_report_reads_gold_havi():
    with patch('pandas.read_sql', return_value=pd.DataFrame()) as mock_read:
        _query_validation_report(MagicMock())
    assert 'gold_havi.ds_validation_report' in mock_read.call_args[0][0]


def test_query_validation_report_returns_none_on_db_error():
    with patch('pandas.read_sql', side_effect=Exception('connection refused')):
        result = _query_validation_report(MagicMock())
    assert result is None


def test_build_stage_summary_shows_all_statuses():
    results = {
        'sqlite_to_bronze': StageResult(success=True, rows_written=5416),
        'bronze_to_silver': StageResult(success=False, errors=['err']),
    }
    stages = ['sqlite_to_bronze', 'bronze_to_silver', 'transform_havi']
    text = _build_stage_summary(results, stages)
    assert 'OK' in text and 'sqlite_to_bronze' in text
    assert 'FAIL' in text and 'bronze_to_silver' in text
    assert 'SKIP' in text and 'transform_havi' in text
    assert '5,416' in text


def test_build_stage_summary_no_rows_for_zero():
    results = {'transform_havi': StageResult(success=True, rows_written=0)}
    text = _build_stage_summary(results, ['transform_havi'])
    assert 'OK' in text
    assert '0' not in text


def test_build_validation_summary_none_returns_unavailable():
    text = _build_validation_summary(None)
    assert 'unavailable' in text.lower()
    assert 'measures_havi' in text


def test_build_validation_summary_groups_by_severity_country_site():
    report = pd.DataFrame({
        'severity': ['ERROR', 'WARNING', 'WARNING'],
        'check': ['dup_id', 'missing_child_records', 'sparse_col'],
        'country': ['Uganda', 'Uganda', 'Uganda'],
        'site': ['Mbarara', 'Mbarara', 'Bushenyi'],
        'record_count': [2, 3, 1],
    })
    text = _build_validation_summary(report)
    assert 'ERRORS' in text
    assert 'WARNINGS' in text
    assert 'Uganda / Mbarara' in text
    assert 'Uganda / Bushenyi' in text
    assert 'dup_id' in text
    assert 'see attachment' in text.lower()


def test_build_validation_summary_empty_df_returns_header_only():
    report = pd.DataFrame(columns=['severity', 'check', 'country', 'site', 'record_count'])
    text = _build_validation_summary(report)
    assert 'ERRORS' not in text
    assert 'WARNINGS' not in text


def _make_email_cfg(tmp_path):
    key = Fernet.generate_key()
    cipher = Fernet(key)
    key_file = tmp_path / 'smtp.key'
    ini_file = tmp_path / 'smtp.ini'
    key_file.write_text(key.decode())
    ini_file.write_text(f"Password={cipher.encrypt(b's3cr3t').decode()}\n")
    return {
        'smtp_host': 'smtp.example.com',
        'smtp_port': 587,
        'sender': 'havi@example.com',
        'smtp_username': 'user@example.com',
        'pipeline_recipients': ['admin@example.com'],
        'field_recipients': ['ug-team@example.com'],
        'keyfiles': {
            'smtp_ini': str(ini_file),
            'smtp_key': str(key_file),
        },
    }


def _config(email_cfg):
    return {'email': email_cfg}


def test_send_pipeline_report_no_config_is_silent():
    send_pipeline_report(
        results={'sqlite_to_bronze': StageResult(success=False)},
        stages=['sqlite_to_bronze'],
        engine=MagicMock(),
        config={},
    )


def test_send_pipeline_report_always_sends_to_pipeline_recipients(tmp_path):
    config = _config(_make_email_cfg(tmp_path))
    results = {'sqlite_to_bronze': StageResult(success=True)}
    clean_report = pd.DataFrame(columns=['severity', 'check', 'country', 'site'])

    mock_smtp_instance = MagicMock()
    with patch('modules.notifier._query_validation_report', return_value=clean_report):
        with patch('smtplib.SMTP') as mock_smtp_cls:
            mock_smtp_cls.return_value.__enter__.return_value = mock_smtp_instance
            send_pipeline_report(
                results=results, stages=['sqlite_to_bronze'],
                engine=MagicMock(), config=config,
            )

    mock_smtp_instance.sendmail.assert_called_once()
    assert mock_smtp_instance.sendmail.call_args[0][1] == ['admin@example.com']


def test_send_pipeline_report_failed_subject_says_failed(tmp_path):
    config = _config(_make_email_cfg(tmp_path))
    results = {'sqlite_to_bronze': StageResult(success=False, errors=['boom'])}

    mock_smtp_instance = MagicMock()
    with patch('modules.notifier._query_validation_report', return_value=None):
        with patch('smtplib.SMTP') as mock_smtp_cls:
            mock_smtp_cls.return_value.__enter__.return_value = mock_smtp_instance
            send_pipeline_report(
                results=results, stages=['sqlite_to_bronze'],
                engine=MagicMock(), config=config,
            )

    msg_string = mock_smtp_instance.sendmail.call_args[0][2]
    assert 'FAILED' in msg_string
    assert 'HAVI Pipeline' in msg_string


def test_send_pipeline_report_field_email_sent_on_issues(tmp_path):
    config = _config(_make_email_cfg(tmp_path))
    results = {'sqlite_to_bronze': StageResult(success=True)}
    report = pd.DataFrame({
        'severity': ['WARNING'], 'check': ['sparse_column'],
        'country': ['Uganda'], 'site': ['Mbarara'],
        'record_count': [2], 'detail': ['test'],
        'affected_ids': ['uid1'],
    })

    sendmail_calls = []
    mock_smtp_instance = MagicMock()
    mock_smtp_instance.sendmail.side_effect = lambda *a, **kw: sendmail_calls.append(a)

    with patch('modules.notifier._query_validation_report', return_value=report):
        with patch('smtplib.SMTP') as mock_smtp_cls:
            mock_smtp_cls.return_value.__enter__.return_value = mock_smtp_instance
            with patch('modules.notifier.date') as mock_date:
                mock_date.today.return_value.weekday.return_value = 4  # Friday
                mock_date.today.return_value.strftime.return_value = '2026-06-05'
                send_pipeline_report(
                    results=results, stages=['sqlite_to_bronze'],
                    engine=MagicMock(), config=config,
                )

    recipients_seen = [call[1] for call in sendmail_calls]
    assert ['admin@example.com'] in recipients_seen
    assert ['ug-team@example.com'] in recipients_seen


def test_send_pipeline_report_does_not_raise_on_smtp_error(tmp_path):
    config = _config(_make_email_cfg(tmp_path))
    results = {'sqlite_to_bronze': StageResult(success=False)}

    with patch('modules.notifier._query_validation_report', return_value=None):
        with patch('smtplib.SMTP', side_effect=smtplib.SMTPException('conn refused')):
            send_pipeline_report(
                results=results, stages=['sqlite_to_bronze'],
                engine=MagicMock(), config=config,
            )
