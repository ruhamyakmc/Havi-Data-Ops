# tests/test_sftp_client.py
import pytest
from unittest.mock import MagicMock, patch

from modules.sftp_client import SFTPClient, select_latest_remote_per_device


def _make_mock_sftp():
    """Return a connected mock SFTPClient context manager."""
    mock_sftp = MagicMock()
    mock_client = MagicMock()
    mock_client.open_sftp.return_value = mock_sftp
    return mock_sftp, mock_client


def test_sftp_client_list_files_returns_filenames():
    mock_sftp, mock_client = _make_mock_sftp()
    attr1, attr2 = MagicMock(), MagicMock()
    attr1.filename = 'havi_entomology_109_2026-04-29_11_00.zip'
    attr2.filename = 'README.txt'
    mock_sftp.listdir_attr.return_value = [attr1, attr2]

    with patch('modules.sftp_client.paramiko.SSHClient', return_value=mock_client):
        with SFTPClient('host', 'user', 'pass') as client:
            result = client.list_files('/Kenya/Sindo/')

    assert result == ['havi_entomology_109_2026-04-29_11_00.zip', 'README.txt']
    mock_sftp.listdir_attr.assert_called_once_with('/Kenya/Sindo/')
    mock_client.set_missing_host_key_policy.assert_called_once()


def test_sftp_client_download_file_calls_get():
    mock_sftp, mock_client = _make_mock_sftp()

    with patch('modules.sftp_client.paramiko.SSHClient', return_value=mock_client):
        with SFTPClient('host', 'user', 'pass') as client:
            client.download_file(
                '/Uganda/havi_entomology_109_2026-04-29_11_00.zip',
                '/local/Extracted/Uganda/havi_entomology_109_2026-04-29_11_00.zip',
            )

    mock_sftp.get.assert_called_once_with(
        '/Uganda/havi_entomology_109_2026-04-29_11_00.zip',
        '/local/Extracted/Uganda/havi_entomology_109_2026-04-29_11_00.zip',
    )


def test_sftp_client_closes_on_exit():
    mock_sftp, mock_client = _make_mock_sftp()

    with patch('modules.sftp_client.paramiko.SSHClient', return_value=mock_client):
        with SFTPClient('host', 'user', 'pass'):
            pass

    mock_sftp.close.assert_called_once()
    mock_client.close.assert_called_once()


def test_sftp_client_connection_error_propagates():
    mock_client = MagicMock()
    mock_client.connect.side_effect = Exception('connection refused')
    with patch('modules.sftp_client.paramiko.SSHClient', return_value=mock_client):
        with pytest.raises(Exception, match='connection refused'):
            with SFTPClient('host', 'user', 'pass'):
                pass
    mock_client.close.assert_called_once()


def test_select_latest_remote_per_device_picks_newest():
    files = [
        'havi_entomology_109_2026-04-29_11_00.zip',
        'havi_entomology_109_2026-04-28_09_00.zip',  # older
        'havi_entomology_110_2026-04-29_08_30.zip',
    ]
    result = select_latest_remote_per_device(files)
    assert result == {
        '109': 'havi_entomology_109_2026-04-29_11_00.zip',
        '110': 'havi_entomology_110_2026-04-29_08_30.zip',
    }


def test_select_latest_remote_per_device_ignores_non_matching():
    files = ['random_file.txt', 'havi_entomology_109_2026-04-29_11_00.zip']
    result = select_latest_remote_per_device(files)
    assert '109' in result
    assert len(result) == 1


def test_select_latest_remote_per_device_empty():
    assert select_latest_remote_per_device([]) == {}
