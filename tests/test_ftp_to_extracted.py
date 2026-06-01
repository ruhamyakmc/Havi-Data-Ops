# tests/test_ftp_to_extracted.py
import os
import pytest
from unittest.mock import MagicMock, patch, call

from stages.ftp_to_extracted import FtpToExtracted


def _make_config(communities=None):
    if communities is None:
        communities = {
            'kenya_nakuru': {
                'community_name': 'Sindo',
                'country': 'kenya',
                'remotefilepath_download': '/Kenya/Sindo/',
            }
        }
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        'ftp': {'hostname': 'ftp.example.com', 'username_havi': 'user'},
        'communities': communities,
        'keyfiles': {
            'ftp_cred_filename_HAVI': 'keyFiles/HAVI_ftp.ini',
            'ftp_key_file_HAVI': 'keyFiles/HAVI_ftp.key',
        },
    }.get(key, default)
    return config


def _mock_sftp(filenames):
    """Return a mock SFTPClient context manager that lists the given filenames."""
    instance = MagicMock()
    instance.__enter__ = MagicMock(return_value=instance)
    instance.__exit__ = MagicMock(return_value=False)
    instance.list_files.return_value = filenames
    instance.download_file.side_effect = lambda remote, local: open(local, 'wb').close()
    return instance


def test_skips_already_downloaded_archive(tmp_path):
    extract_dir = tmp_path / 'Extracted' / 'Kenya'
    extract_dir.mkdir(parents=True)
    # Pre-create the archive file so it is "already downloaded"
    (extract_dir / 'havi_entomology_109_2026-04-29_11_00.zip').touch()

    stage = FtpToExtracted(config=_make_config(), engine=MagicMock())

    with patch('stages.ftp_to_extracted.get_decrypted_password', return_value='s'):
        with patch('stages.ftp_to_extracted.SFTPClient',
                   return_value=_mock_sftp(['havi_entomology_109_2026-04-29_11_00.zip'])):
            with patch('stages.ftp_to_extracted.select_files_for_download',
                       return_value={'109': 'havi_entomology_109_2026-04-29_11_00.zip'}):
                with patch('stages.ftp_to_extracted.get_country_paths', return_value={
                    'extract_path': str(extract_dir),
                }):
                    result = stage.run()

    assert result.success
    assert result.rows_written == 0


def test_downloads_and_validates_archive(tmp_path):
    stage = FtpToExtracted(config=_make_config(), engine=MagicMock())

    mock_zip = MagicMock()
    mock_zip.__enter__ = MagicMock(return_value=mock_zip)
    mock_zip.__exit__ = MagicMock(return_value=False)
    mock_zip.testzip.return_value = None  # no corrupt files

    with patch('stages.ftp_to_extracted.get_decrypted_password', return_value='s'):
        with patch('stages.ftp_to_extracted.SFTPClient',
                   return_value=_mock_sftp(['havi_entomology_109_2026-04-29_11_00.zip'])):
            with patch('stages.ftp_to_extracted.get_country_paths', return_value={
                'extract_path': str(tmp_path / 'Extracted' / 'Kenya'),
            }):
                with patch('stages.ftp_to_extracted.zipfile.ZipFile',
                           return_value=mock_zip):
                    result = stage.run()

    assert result.success
    assert result.rows_written == 1
    mock_zip.testzip.assert_called_once()


def test_sftp_connection_failure_is_non_fatal():
    stage = FtpToExtracted(config=_make_config(), engine=MagicMock())

    with patch('stages.ftp_to_extracted.get_decrypted_password', return_value='s'):
        with patch('stages.ftp_to_extracted.SFTPClient',
                   side_effect=Exception('connection refused')):
            with patch('stages.ftp_to_extracted.get_country_paths', return_value={
                'extract_path': '/fake/Extracted/Kenya',
            }):
                with patch('stages.ftp_to_extracted.os.makedirs'):
                    result = stage.run()

    assert not result.success
    assert any('connection refused' in e for e in result.errors)


def test_sftp_failure_for_one_country_continues_others(tmp_path):
    communities = {
        'kenya_nakuru': {
            'country': 'kenya',
            'remotefilepath_download': '/Kenya/Sindo/',
        },
        'uganda_mbarara': {
            'country': 'uganda',
            'remotefilepath_download': '/Uganda/Mbarara/',
        },
    }
    stage = FtpToExtracted(config=_make_config(communities), engine=MagicMock())

    call_count = {'n': 0}

    def sftp_side_effect(*args, **kwargs):
        call_count['n'] += 1
        if call_count['n'] == 1:
            raise Exception('kenya SFTP failed')
        return _mock_sftp([])

    with patch('stages.ftp_to_extracted.get_decrypted_password', return_value='s'):
        with patch('stages.ftp_to_extracted.SFTPClient', side_effect=sftp_side_effect):
            with patch('stages.ftp_to_extracted.get_country_paths', return_value={
                'extract_path': str(tmp_path / 'Extracted'),
            }):
                with patch('stages.ftp_to_extracted.os.makedirs'):
                    result = stage.run()

    assert len(result.errors) == 1
    assert 'kenya SFTP failed' in result.errors[0]


def test_per_device_corrupt_zip_continues_other_devices(tmp_path):
    stage = FtpToExtracted(config=_make_config(), engine=MagicMock())

    sftp_mock = _mock_sftp([
        'havi_entomology_109_2026-04-29_11_00.zip',
        'havi_entomology_110_2026-04-29_11_00.zip',
    ])

    zip_calls = {'n': 0}

    def fake_zip(*args, **kwargs):
        zip_calls['n'] += 1
        if zip_calls['n'] == 1:
            raise Exception('corrupt zip')
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=m)
        m.__exit__ = MagicMock(return_value=False)
        m.testzip.return_value = None
        return m

    with patch('stages.ftp_to_extracted.get_decrypted_password', return_value='s'):
        with patch('stages.ftp_to_extracted.SFTPClient', return_value=sftp_mock):
            with patch('stages.ftp_to_extracted.get_country_paths', return_value={
                'extract_path': str(tmp_path / 'Extracted' / 'Kenya'),
            }):
                with patch('stages.ftp_to_extracted.zipfile.ZipFile',
                           side_effect=fake_zip):
                    with patch('stages.ftp_to_extracted.os.remove'):
                        with patch('stages.ftp_to_extracted._MAX_WORKERS', 1):
                            result = stage.run()

    assert result.success             # partial success — downstream should run
    assert result.rows_written == 1
    assert len(result.warnings) == 1  # corrupt archive is a warning, not a hard error
    assert result.warnings[0]['check'] == 'corrupt_archive'


def test_all_devices_corrupt_returns_success_with_warnings(tmp_path):
    stage = FtpToExtracted(config=_make_config(), engine=MagicMock())

    sftp_mock = _mock_sftp(['havi_entomology_109_2026-04-29_11_00.zip'])

    with patch('stages.ftp_to_extracted.get_decrypted_password', return_value='s'):
        with patch('stages.ftp_to_extracted.SFTPClient', return_value=sftp_mock):
            with patch('stages.ftp_to_extracted.get_country_paths', return_value={
                'extract_path': str(tmp_path / 'Extracted' / 'Kenya'),
            }):
                with patch('stages.ftp_to_extracted.zipfile.ZipFile',
                           side_effect=Exception('corrupt')):
                    with patch('stages.ftp_to_extracted.os.remove'):
                        result = stage.run()

    # Corrupt archives are non-fatal warnings — stage still succeeds (no hard errors)
    assert result.success
    assert result.rows_written == 0
    assert len(result.warnings) == 1
    assert result.warnings[0]['check'] == 'corrupt_archive'


def test_download_retried_on_network_error(tmp_path):
    """A flaky download that fails twice then succeeds on the third attempt."""
    stage = FtpToExtracted(config=_make_config(), engine=MagicMock())

    mock_zip = MagicMock()
    mock_zip.__enter__ = MagicMock(return_value=mock_zip)
    mock_zip.__exit__ = MagicMock(return_value=False)
    mock_zip.testzip.return_value = None

    download_attempts = {'n': 0}

    def flaky_sftp(*args, **kwargs):
        instance = _mock_sftp(['havi_entomology_109_2026-04-29_11_00.zip'])
        def flaky_download(remote, local):
            download_attempts['n'] += 1
            if download_attempts['n'] < 3:
                raise Exception('network error')
            open(local, 'wb').close()
        instance.download_file = MagicMock(side_effect=flaky_download)
        return instance

    with patch('stages.ftp_to_extracted.get_decrypted_password', return_value='s'):
        with patch('stages.ftp_to_extracted.SFTPClient', side_effect=flaky_sftp):
            with patch('stages.ftp_to_extracted.get_country_paths', return_value={
                'extract_path': str(tmp_path / 'Extracted' / 'Kenya'),
            }):
                with patch('stages.ftp_to_extracted.zipfile.ZipFile',
                           return_value=mock_zip):
                    result = stage.run()

    assert result.success
    assert result.rows_written == 1
    assert download_attempts['n'] == 3   # failed twice, succeeded on third
