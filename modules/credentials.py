from __future__ import annotations

from cryptography.fernet import Fernet


def load_encrypted_value(cred_filename: str, key_file: str, key_name: str = 'Password') -> str:
    """Decrypt a Fernet-encrypted value from a simple key=value credential file."""
    with open(key_file, 'r') as f:
        key = f.read().strip().encode()

    cipher = Fernet(key)
    config: dict[str, str] = {}
    with open(cred_filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            config[k.strip()] = v.strip()

    if key_name not in config:
        raise KeyError(f"'{key_name}' key not found in credential file: {cred_filename}")

    return cipher.decrypt(config[key_name].encode()).decode()
