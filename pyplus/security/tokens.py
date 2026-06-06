"""
Per-user HMAC tokens for unauthenticated HTTP endpoints (iCal subscription).

The token is HMAC-SHA256(secret_key, "ical:<user_id>"), truncated to 18 bytes
and base64url-encoded.  It is:
  - Stable: same key + user_id → same token every time (no timestamp)
  - Unforgeable without the app secret key
  - Invalidated if PYPLUS_SECRET_KEY is rotated

These tokens are safe to embed in calendar subscription URLs because calendar
apps make bare GET requests without cookies or session context.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

# HKDF info label for the iCal HMAC subkey — separates it from the credential
# encryption key and the cookie-signing key so they don't share raw key material.
_ICAL_INFO = b"pyplus/ical/v1"
_UNSET = object()


def _resolve_key(secret_key: object) -> str | None:
    """Resolve the master key: sentinel → configured key; otherwise the override."""
    if secret_key is _UNSET:
        from pyplus.config import settings

        return settings.secret_key or None
    return secret_key or None  # type: ignore[return-value]


def _token_from_key(key: bytes, user_id: int) -> str:
    digest = hmac.new(key, f"ical:{user_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode().rstrip("=")


def make_ical_token(user_id: int, secret_key: object = _UNSET) -> str | None:
    """Return URL-safe token for the given user, or None if no key is available.

    Uses an HKDF-derived subkey (not the raw master key). `secret_key` overrides
    the configured key (mainly for tests).
    """
    from pyplus.security.secrets import derive_key

    master = _resolve_key(secret_key)
    if master is None:
        return None
    sub = derive_key(_ICAL_INFO, length=32, master=master)
    if sub is None:
        return None
    return _token_from_key(sub, user_id)


def verify_ical_token(token: str, user_id: int, secret_key: object = _UNSET) -> bool:
    """Constant-time verification. Accepts the current (derived-key) token and the
    legacy (raw master-key) token so calendar subscriptions created before key
    separation keep working. Returns False if no key is available."""
    master = _resolve_key(secret_key)
    if master is None:
        return False
    candidates = [make_ical_token(user_id, secret_key)]
    # Legacy scheme: HMAC directly with the raw master key.
    candidates.append(_token_from_key(master.encode(), user_id))
    return any(c is not None and hmac.compare_digest(token, c) for c in candidates)
