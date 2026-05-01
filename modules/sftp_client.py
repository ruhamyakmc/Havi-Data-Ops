# modules/sftp_client.py
from __future__ import annotations

import logging
import paramiko
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_DEVICE_ARCHIVE_RE = re.compile(
    r'^havi_entomology_(\d+)_(\d{4}-\d{2}-\d{2}_\d{2}_\d{2})\.zip$',
    re.IGNORECASE,
)


def select_latest_remote_per_device(filenames: list[str]) -> dict[str, str]:
    """
    Return {device_id: filename} for the latest .zip per device.
    Filename format: havi_entomology_{device_id}_{YYYY-MM-DD_HH_MM}.zip
    Non-matching filenames are silently ignored.
    """
    latest: dict[str, tuple[datetime, str]] = {}
    for name in filenames:
        m = _DEVICE_ARCHIVE_RE.match(name)
        if not m:
            continue
        device_id = m.group(1)
        ts = datetime.strptime(m.group(2), '%Y-%m-%d_%H_%M')
        existing_ts, _ = latest.get(device_id, (datetime.min, ''))
        if ts > existing_ts:
            latest[device_id] = (ts, name)
    return {device_id: fname for device_id, (_, fname) in latest.items()}


class SFTPClient:
    """
    Minimal paramiko SFTP wrapper. Use as a context manager — the connection
    is opened on entry and closed on exit regardless of exceptions.
    """

    def __init__(self, hostname: str, username: str, password: str) -> None:
        self._hostname = hostname
        self._username = username
        self._password = password
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None

    def __enter__(self) -> 'SFTPClient':
        self._client = paramiko.SSHClient()
        self._client.load_system_host_keys()
        # Load project-managed known_hosts (takes precedence over system file).
        _known_hosts = '/app/secrets/known_hosts'
        try:
            self._client.load_host_keys(_known_hosts)
        except FileNotFoundError:
            pass  # outside Docker; system known_hosts only
        self._client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            self._client.connect(
                self._hostname,
                username=self._username,
                password=self._password,
            )
            self._sftp = self._client.open_sftp()
        except Exception:
            self._client.close()
            raise
        logger.info(f"Connected to SFTP: {self._hostname}")
        return self

    def __exit__(self, *args) -> None:
        if self._sftp:
            self._sftp.close()
        if self._client:
            self._client.close()
        logger.info(f"Disconnected from SFTP: {self._hostname}")

    def list_files(self, remote_path: str) -> list[str]:
        """Return filenames (not full paths) in remote_path."""
        return [attr.filename for attr in self._sftp.listdir_attr(remote_path)]

    def download_file(self, remote_path: str, local_path: str) -> None:
        """Download remote_path to local_path."""
        self._sftp.get(remote_path, local_path)
        logger.info(f"Downloaded: {remote_path} → {local_path}")
