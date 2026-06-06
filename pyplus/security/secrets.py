"""Fernet-based encryption for stored PLUS credentials.

The key comes from PYPLUS_SECRET_KEY env var. If absent, encryption is
unavailable and remember-me is disabled — this is fail-safe, not a bypass.

The master key is never used directly for more than one purpose. `derive_key`
produces purpose-specific subkeys via HKDF so a leak in one context (cookie
signing, iCal HMAC) cannot decrypt credentials, and rotating one purpose does not
forcibly break the others. Encryption uses a derived subkey; `decrypt` falls back
to the legacy master-key Fernet so credentials written before this change still
decrypt (they re-encrypt with the derived key on the next remember-me save).
"""

from __future__ import annotations

import base64
import logging

log = logging.getLogger(__name__)

# HKDF info label for the credential-encryption subkey.
_FERNET_INFO = b"pyplus/fernet/v1"

_fernet = None
_legacy_fernet = None


def derive_key(info: bytes, length: int = 32, master: str | None = None) -> bytes | None:
    """Derive a purpose-specific subkey via HKDF-SHA256.

    `master` defaults to the configured PYPLUS_SECRET_KEY; pass it explicitly to
    derive from a specific key (used by token helpers for testability). Returns
    None when no key is available. `info` domain-separates each purpose
    (e.g. b"pyplus/cookie/v1", b"pyplus/ical/v1").
    """
    if master is None:
        from pyplus.config import settings

        master = settings.secret_key
    if not master:
        return None
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info).derive(
        master.encode()
    )


def _get_fernet():
    """Fernet using a key derived from the master (current write key)."""
    global _fernet
    if _fernet is not None:
        return _fernet
    sub = derive_key(_FERNET_INFO)
    if sub is None:
        return None
    try:
        from cryptography.fernet import Fernet

        _fernet = Fernet(base64.urlsafe_b64encode(sub))
        return _fernet
    except Exception as exc:
        log.error("Could not initialise Fernet from PYPLUS_SECRET_KEY: %s", exc)
        return None


def _get_legacy_fernet():
    """Fernet using the raw master key — only for decrypting pre-HKDF ciphertext."""
    global _legacy_fernet
    if _legacy_fernet is not None:
        return _legacy_fernet
    from pyplus.config import settings

    if not settings.secret_key:
        return None
    try:
        from cryptography.fernet import Fernet

        _legacy_fernet = Fernet(settings.secret_key.encode())
        return _legacy_fernet
    except Exception:
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
    """Decrypt Fernet ciphertext. Returns None on failure or missing key.

    Tries the derived key first, then the legacy master-key Fernet so ciphertext
    written before key separation still decrypts.
    """
    token = ciphertext.encode()
    for f in (_get_fernet(), _get_legacy_fernet()):
        if f is None:
            continue
        try:
            return f.decrypt(token).decode()
        except Exception:
            continue
    return None
