import pytest
from modules.config import ConfigLoader
import json

def _write_config(tmp_path, data):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return str(p)

BASE = {
    "communities": {"uganda": {"community_name": "Uganda", "country": "uganda", "remotefilepath_download": "/data/"}},
    "ftp": {"hostname": "h", "username_havi": "u"},
    "keyfiles": {"ftp_cred_filename_HAVI": "a", "ftp_key_file_HAVI": "b"},
}

def test_config_requires_db_block(tmp_path):
    data = {**BASE,
            "trial": {"name": "havi", "dedup_key": "uniqueid", "dedup_strategy": "latest_snapshot"},
            "schedule": {"pipeline_cron": "0 6 * * *"}}
    cfg = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="db"):
        ConfigLoader(cfg)

def test_config_requires_trial_block(tmp_path):
    data = {**BASE, "db": {"host": "db", "port": 5432, "name": "havi", "user": "u", "password_secret_file": "pw"}}
    cfg = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="trial"):
        ConfigLoader(cfg)

def test_config_requires_schedule_block(tmp_path):
    data = {**BASE,
            "db": {"host": "db", "port": 5432, "name": "havi", "user": "u", "password_secret_file": "pw"},
            "trial": {"name": "havi", "dedup_key": "uniqueid", "dedup_strategy": "latest_snapshot"}}
    cfg = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="schedule"):
        ConfigLoader(cfg)

def test_config_valid_full(tmp_path):
    data = {**BASE,
            "db": {"host": "db", "port": 5432, "name": "havi", "user": "u", "password_secret_file": "pw"},
            "trial": {"name": "havi", "dedup_key": "uniqueid", "dedup_strategy": "latest_snapshot"},
            "schedule": {"pipeline_cron": "0 6 * * *"}}
    cfg = _write_config(tmp_path, data)
    loader = ConfigLoader(cfg)
    assert loader.get('trial')['name'] == 'havi'


def test_config_requires_nested_db_password_secret_file(tmp_path):
    data = {**BASE,
            "db": {"host": "db", "port": 5432, "name": "havi", "user": "u"},
            "trial": {"name": "havi", "dedup_key": "uniqueid", "dedup_strategy": "latest_snapshot"},
            "schedule": {"pipeline_cron": "0 6 * * *"}}
    cfg = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="db.password_secret_file"):
        ConfigLoader(cfg)
