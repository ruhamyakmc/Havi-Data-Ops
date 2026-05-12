from __future__ import annotations

import html as _html
import io
import logging
import smtplib
import ssl
from datetime import date
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
from cryptography.fernet import Fernet

from stages.base import StageResult

logger = logging.getLogger(__name__)


def _load_smtp_password(ini_path: str, key_path: str) -> str:
    """Read the Fernet-encrypted Password value from an ini-style file."""
    with open(key_path, 'r') as f:
        key = f.read().strip().encode()
    cipher = Fernet(key)

    cfg: dict[str, str] = {}
    with open(ini_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            cfg[k.strip()] = v.strip()

    if 'Password' not in cfg:
        raise KeyError("'Password' key not found in SMTP credential file.")

    return cipher.decrypt(cfg['Password'].encode()).decode()


def _query_validation_report(engine) -> pd.DataFrame | None:
    """Query the HAVI validation report if it exists."""
    try:
        return pd.read_sql('SELECT * FROM gold_havi.ds_validation_report', engine)
    except Exception as exc:
        logger.warning("Could not query ds_validation_report: %s", exc)
        return None


def _build_stage_summary(
    results: dict[str, StageResult],
    stages: list[str],
) -> str:
    sep = '-' * 47
    lines = ['Stage Results', sep]
    for name in stages:
        if name not in results:
            lines.append(f'  SKIP  {name:<28}  skipped')
        elif results[name].success:
            rw = results[name].rows_written
            row_str = f'{rw:,} rows' if rw else ''
            lines.append(f'  OK    {name:<28}  {row_str}')
        else:
            lines.append(f'  FAIL  {name:<28}  FAILED')
    lines.append(sep)
    return '\n'.join(lines)


def _build_validation_summary(report_df: pd.DataFrame | None) -> str:
    """Concise summary for the email body; full detail is in the CSV attachment."""
    if report_df is None:
        return 'Validation report unavailable - measures_havi did not run.\n'

    sep = '-' * 47
    lines = ['Validation Issues (see attachment for full detail)', sep]

    for severity in ['ERROR', 'WARNING']:
        subset = report_df[report_df['severity'] == severity]
        if subset.empty:
            continue
        lines.append(f'\n  {severity}S ({len(subset)} issue row(s)):')
        group_cols = [c for c in ['country', 'site', 'mrccode'] if c in subset.columns]
        if group_cols:
            grouped = subset.groupby(group_cols, sort=True, dropna=False)
            for keys, group in grouped:
                if not isinstance(keys, tuple):
                    keys = (keys,)
                header = ' / '.join(str(k) for k in keys if pd.notna(k) and str(k))
                lines.append(f'    {header or "all"}')
                for check, cnt in group.groupby('check').size().items():
                    lines.append(f'      - {check} ({cnt})')
        else:
            for check, cnt in subset.groupby('check').size().items():
                lines.append(f'    - {check} ({cnt})')

    lines.append(sep)
    return '\n'.join(lines)


def _attach_csv(msg: MIMEMultipart, df: pd.DataFrame, filename: str) -> None:
    """Sanitize and attach a DataFrame as a UTF-8 CSV to a MIME message."""
    csv_buffer = io.StringIO()
    safe_df = df.copy()
    for col in safe_df.select_dtypes(include='object').columns:
        safe_df.loc[:, col] = safe_df[col].map(
            lambda v: ("'" + v)
            if isinstance(v, str) and v and v[0] in ('=', '+', '-', '@', '\t', '\r')
            else v
        )
    safe_df.to_csv(csv_buffer, index=False)
    part = MIMEBase('application', 'octet-stream')
    part.set_payload(csv_buffer.getvalue().encode('utf-8-sig'))
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
    msg.attach(part)


def _send(
    email_cfg: dict,
    recipients: list[str],
    subject: str,
    plain: str,
    html: str,
    attachment_df: pd.DataFrame | None = None,
    attachment_filename: str | None = None,
) -> None:
    """Assemble a multipart email and send it via SMTP with STARTTLS."""
    ini_path = email_cfg['keyfiles']['smtp_ini']
    key_path = email_cfg['keyfiles']['smtp_key']
    username = email_cfg['smtp_username']
    password = _load_smtp_password(ini_path, key_path)

    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From'] = email_cfg['sender']
    msg['To'] = ', '.join(recipients)

    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(plain, 'plain'))
    alt.attach(MIMEText(html, 'html'))
    msg.attach(alt)

    if attachment_df is not None:
        filename = attachment_filename or f'havi_validation_{date.today().strftime("%Y-%m-%d")}.csv'
        _attach_csv(msg, attachment_df, filename)

    with smtplib.SMTP(email_cfg['smtp_host'], email_cfg['smtp_port']) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(username, password)
        smtp.sendmail(email_cfg['sender'], recipients, msg.as_string())


def send_pipeline_report(
    results: dict[str, StageResult],
    stages: list[str],
    engine,
    config,
) -> None:
    """
    Send HAVI pipeline status and field data quality emails.

    SMTP errors are caught and logged so notification issues never mask ETL results.
    """
    email_cfg = config.get('email')
    if not email_cfg:
        return

    report_df = _query_validation_report(engine)

    stage_warnings = [w for r in results.values() for w in r.warnings]
    if stage_warnings:
        warnings_df = pd.DataFrame(stage_warnings)
        report_df = (
            pd.concat([warnings_df, report_df], ignore_index=True)
            if report_df is not None else warnings_df
        )

    has_failures = any(not r.success for r in results.values())
    today = date.today().strftime('%d %b %Y')
    stage_section = _build_stage_summary(results, stages)

    pipeline_recipients = email_cfg.get('pipeline_recipients', [])
    if pipeline_recipients:
        status = 'FAILED' if has_failures else 'Run complete'
        subject = f'HAVI Pipeline - {status} ({today})'
        html = f'<pre style="font-family:monospace;font-size:13px">{_html.escape(stage_section)}</pre>'
        try:
            _send(email_cfg, pipeline_recipients, subject, stage_section, html)
            logger.info('Pipeline status email sent to %s.', pipeline_recipients)
        except Exception as exc:
            logger.error('Notifier failed for pipeline recipients: %s', exc)

    field_recipients = email_cfg.get('field_recipients', [])
    if not field_recipients or report_df is None or report_df.empty:
        return
    if 'severity' not in report_df.columns or not report_df['severity'].isin(['ERROR', 'WARNING']).any():
        return

    validation_section = _build_validation_summary(report_df)
    subject = f'HAVI Data Quality - issues found ({today})'
    plain = f'{stage_section}\n\n{validation_section}'
    html = f'<pre style="font-family:monospace;font-size:13px">{_html.escape(plain)}</pre>'
    try:
        _send(email_cfg, field_recipients, subject, plain, html, attachment_df=report_df)
        logger.info('Field quality report sent to %s.', field_recipients)
    except Exception as exc:
        logger.error('Notifier failed for field recipients %s: %s', field_recipients, exc)
