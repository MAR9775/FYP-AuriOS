"""crypto.py — Symmetric encryption utilities for AuriOS."""

import os
from pathlib import Path
from cryptography.fernet import Fernet

BASE_DIR = Path(__file__).resolve().parent.parent.parent
KEY_PATH = BASE_DIR / "data" / ".secret.key"

def _get_or_create_key() -> bytes:
    """Load the existing key or generate a new one if missing."""
    if KEY_PATH.exists():
        with open(KEY_PATH, "rb") as f:
            return f.read()
    else:
        # Ensure data dir exists
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        with open(KEY_PATH, "wb") as f:
            f.write(key)
        # Attempt to hide the file on Windows
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(KEY_PATH), 2)  # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            pass
        return key

def get_fernet() -> Fernet:
    return Fernet(_get_or_create_key())

def encrypt_data(plain_text: str) -> str:
    """Encrypt a plain text string to a secure URL-safe base64 encoded string."""
    if not plain_text:
        return ""
    f = get_fernet()
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")

def decrypt_data(cipher_text: str) -> str:
    """Decrypt a secure URL-safe base64 encoded string back to plain text."""
    if not cipher_text:
        return ""
    f = get_fernet()
    try:
        return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        raise ValueError(f"Failed to decrypt data: {e}")
