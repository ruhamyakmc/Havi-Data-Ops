# stages/ftp_to_extracted.py
from __future__ import annotations

import logging
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from modules.config import get_country_paths
from modules.sftp_client import SFTPClient, select_files_for_download
from modules.utils import get_decrypted_password
from stages.base import BaseStage, StageResult

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_RETRIES = 3
_MAX_WORKERS = 4


def _download_with_retry(
    hostname: str,
    username: str,
    ftp_password: str,
    remote_path: str,
    filename: str,
    local_archive: str,
) -> None:
    last_exc: Exception = Exception('no attempts made')
    for attempt in range(1, _MAX_DOWNLOAD_RETRIES + 1):
        try:
            with SFTPClient(hostname, username, ftp_password) as sftp:
                sftp.download_file(remote_path + filename, local_archive)
            return
        except Exception as exc:
            last_exc = exc
            logger.warning(
                f"Download attempt {attempt}/{_MAX_DOWNLOAD_RETRIES} failed "
                f"for '{filename}': {exc}"
            )
            if attempt < _MAX_DOWNLOAD_RETRIES:
                time.sleep(2 ** attempt)
    raise last_exc


def _process_device(
    hostname: str,
    username: str,
    ftp_password: str,
    remote_path: str,
    filename: str,
    extract_dir: str,
    country: str,
) -> tuple[int, str | None, dict | None]:
    """
    Download and validate one device zip archive.
    Returns:
      (1, None, None)       — success
      (0, None, None)       — skipped (already downloaded)
      (0, error_msg, None)  — fatal: SFTP/download failure
      (0, None, warn_dict)  — non-fatal: corrupt zip
    """
    local_archive = os.path.join(extract_dir, filename)
    partial_archive = f'{local_archive}.part'

    if os.path.exists(local_archive):
        logger.info(f"[{country}] Skipping {filename} — already downloaded.")
        return 0, None, None
    if os.path.exists(partial_archive):
        logger.warning(f"[{country}] Removing stale partial download: {partial_archive}")
        os.remove(partial_archive)

    try:
        _download_with_retry(
            hostname, username, ftp_password,
            remote_path, filename, partial_archive,
        )
    except Exception as exc:
        msg = f"[{country}] Failed to download '{filename}': {exc}"
        logger.error(msg)
        if os.path.exists(partial_archive):
            os.remove(partial_archive)
        return 0, msg, None

    try:
        with zipfile.ZipFile(partial_archive, 'r') as zf:
            zf.testzip()  # raises BadZipFile if corrupt
        os.replace(partial_archive, local_archive)
        logger.info(f"[{country}] Downloaded {filename}")
        return 1, None, None
    except Exception as exc:
        logger.warning(f"[{country}] Corrupt zip '{filename}': {exc} — skipping.")
        if os.path.exists(partial_archive):
            quarantine_dir = os.path.join(extract_dir, 'quarantine')
            os.makedirs(quarantine_dir, exist_ok=True)
            os.replace(partial_archive, os.path.join(quarantine_dir, filename))
        warning = dict(
            check='corrupt_archive',
            severity='ERROR',
            country=country,
            site=None,
            field='archive',
            record_count=1,
            detail=f"Archive '{filename}' could not be read: {exc}",
            affected_subjids=None,
            affected_tablets=filename,
        )
        return 0, None, warning


class FtpToExtracted(BaseStage):
    name = 'ftp_to_extracted'
    dependencies: list[str] = []

    def run(self) -> StageResult:
        ftp = self.config.get('ftp') or {}
        communities = self.config.get('communities') or {}
        keyfiles = self.config.get('keyfiles') or {}

        hostname = ftp['hostname']
        username = ftp['username_havi']
        ftp_password = get_decrypted_password(
            keyfiles['ftp_cred_filename_HAVI'],
            keyfiles['ftp_key_file_HAVI'],
        )

        total_downloaded = 0
        errors: list[str] = []
        warnings: list[dict] = []

        for community_key, community in communities.items():
            country = community['country']
            remote_path = community['remotefilepath_download']
            paths = get_country_paths(country)
            extract_dir = paths['extract_path']

            try:
                os.makedirs(extract_dir, exist_ok=True)

                with SFTPClient(hostname, username, ftp_password) as sftp:
                    filenames = sftp.list_files(remote_path)

                latest = select_files_for_download(filenames)
                logger.info(
                    f"[{country}] {len(latest)} zip archive(s) selected for download "
                    f"({len(filenames)} total on FTP)."
                )
                if not latest:
                    warnings.append(dict(
                        check='no_new_files',
                        severity='WARNING',
                        country=country,
                        site=None,
                        field='archive',
                        record_count=0,
                        detail='No HAVI device zip archives were found on the SFTP server.',
                        affected_subjids=None,
                        affected_tablets=None,
                    ))
                    continue

                with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
                    futures = {
                        executor.submit(
                            _process_device,
                            hostname, username, ftp_password,
                            remote_path, filename, extract_dir, country,
                        ): filename
                        for filename in sorted(latest.values())
                    }
                    for future in as_completed(futures):
                        downloaded, error_msg, warning = future.result()
                        total_downloaded += downloaded
                        if error_msg:
                            errors.append(error_msg)
                        if warning:
                            warnings.append(warning)

            except Exception as exc:
                msg = f"[{country}] SFTP connection failed: {exc}"
                logger.error(msg)
                errors.append(msg)

        return StageResult(
            success=len(errors) == 0,
            rows_written=total_downloaded,
            errors=errors,
            warnings=warnings,
        )
