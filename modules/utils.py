# modules/utils.py
from __future__ import annotations

from modules.credentials import load_encrypted_value


def get_decrypted_password(cred_filename: str, key_file: str) -> str:
    """
    Decrypt a Fernet-encrypted password from a credential file.
    File format: key=value lines; blank lines and lines starting with # are ignored.
    Raises KeyError if 'Password' key is absent.
    """
    return load_encrypted_value(cred_filename, key_file, 'Password')
