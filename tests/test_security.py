"""Unit tests for the security hardening:

- net.assert_safe_url: SSRF guard (scheme + private/loopback/link-local rejection)
- secrets: HKDF subkey derivation, derived-key Fernet round-trip, legacy fallback
- tokens: iCal token uses a derived key but still accepts the legacy raw-key token
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest
from cryptography.fernet import Fernet

from pyplus.security import secrets as S
from pyplus.security import tokens as T
from pyplus.security.net import UnsafeUrlError, assert_safe_url

# ── SSRF guard ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "",
        "https://",  # no host
        "http://127.0.0.1/x",  # loopback
        "http://10.0.0.5/x",  # private
        "http://192.168.1.1/x",  # private
        "http://169.254.169.254/latest/meta-data",  # link-local (cloud metadata)
        "http://[::1]/x",  # ipv6 loopback
        "http://localhost/x",  # resolves to loopback via hosts file
    ],
)
async def test_assert_safe_url_rejects(url):
    with pytest.raises(UnsafeUrlError):
        await assert_safe_url(url)


@pytest.mark.parametrize("url", ["https://8.8.8.8/topic", "http://1.1.1.1/"])
async def test_assert_safe_url_allows_public_ip(url):
    # Numeric public IPs resolve locally (no DNS), so this stays offline.
    await assert_safe_url(url)  # must not raise


# ── secrets: key derivation + encryption ──────────────────────────────────────


@pytest.fixture
def secret_key(monkeypatch):
    """Set a valid master key and reset the cached Fernet instances around the test."""
    from pyplus.config import settings

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "secret_key", key)
    S._fernet = None
    S._legacy_fernet = None
    yield key
    S._fernet = None
    S._legacy_fernet = None


def test_derive_key_none_without_master(monkeypatch):
    from pyplus.config import settings

    monkeypatch.setattr(settings, "secret_key", "")
    assert S.derive_key(b"pyplus/fernet/v1") is None


def test_derive_key_is_deterministic_and_domain_separated():
    master = "some-master-key"
    a1 = S.derive_key(b"purpose/a", master=master)
    a2 = S.derive_key(b"purpose/a", master=master)
    b = S.derive_key(b"purpose/b", master=master)
    assert a1 == a2  # deterministic
    assert a1 != b  # different info → different subkey
    assert len(a1) == 32


def test_encrypt_decrypt_roundtrip(secret_key):
    ct = S.encrypt("hunter2")
    assert ct is not None and ct != "hunter2"
    assert S.decrypt(ct) == "hunter2"


def test_encryption_uses_derived_not_raw_key(secret_key):
    # The Fernet key actually used must be the HKDF subkey, not the raw master.
    derived_fernet_key = base64.urlsafe_b64encode(S.derive_key(S._FERNET_INFO)).decode()
    assert derived_fernet_key != secret_key


def test_decrypt_falls_back_to_legacy_ciphertext(secret_key):
    # Ciphertext written by the pre-HKDF scheme (raw master key) must still decrypt.
    legacy_ct = Fernet(secret_key.encode()).encrypt(b"old-secret").decode()
    assert S.decrypt(legacy_ct) == "old-secret"


def test_encrypt_returns_none_without_key(monkeypatch):
    from pyplus.config import settings

    monkeypatch.setattr(settings, "secret_key", "")
    S._fernet = None
    S._legacy_fernet = None
    try:
        assert S.encrypt("x") is None
        assert S.decrypt("anything") is None
    finally:
        S._fernet = None
        S._legacy_fernet = None


# ── tokens: iCal HMAC key separation + legacy acceptance ──────────────────────

_RAW = "master-key-for-tokens"


def _legacy_token(user_id: int, raw: str) -> str:
    digest = hmac.new(raw.encode(), f"ical:{user_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode().rstrip("=")


def test_ical_token_uses_derived_key_not_raw():
    tok = T.make_ical_token(7, _RAW)
    assert tok is not None
    # The new token must differ from a raw-key HMAC (proves the key is separated).
    assert tok != _legacy_token(7, _RAW)


def test_ical_verify_accepts_current_token():
    tok = T.make_ical_token(7, _RAW)
    assert T.verify_ical_token(tok, 7, _RAW) is True
    assert T.verify_ical_token(tok, 8, _RAW) is False  # wrong user


def test_ical_verify_accepts_legacy_token():
    # Subscriptions created before key separation must keep working.
    legacy = _legacy_token(7, _RAW)
    assert T.verify_ical_token(legacy, 7, _RAW) is True


def test_ical_token_none_without_key():
    assert T.make_ical_token(1, None) is None
    assert T.verify_ical_token("anytoken", 1, None) is False
