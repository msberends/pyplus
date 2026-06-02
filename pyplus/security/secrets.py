"""Fernet-based encryption for stored PLUS credentials.

The key comes from PYPLUS_SECRET_KEY env var. If absent, encryption is
unavailable and remember-me is disabled — this is fail-safe, not a bypass.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    from pyplus.config import settings

    if not settings.secret_key:
        return None
    try:
        from cryptography.fernet import Fernet

        _fernet = Fernet(settings.secret_key.encode())
        return _fernet
    except Exception as exc:
        log.error("Invalid PYPLUS_SECRET_KEY: %s", exc)
        return None


def is_available() -> bool:
    return _get_fernet() is not None


def encrypt(plaintext: str) -> str | None:
    """Return Fernet-encrypted ciphertext, or None if encryption is unavailable."""
    f = _get_fernet()
    if f is None:
        return None
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    """Decrypt Fernet ciphertext. Returns None on failure or missing key."""
    f = _get_fernet()
    if f is None:
        return None
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        return None
