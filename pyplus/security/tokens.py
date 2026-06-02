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

_UNSET = object()


def make_ical_token(user_id: int, secret_key: str | None = _UNSET) -> str | None:  # type: ignore[assignment]
    """Return URL-safe token for the given user, or None if no secret key is set."""
    if secret_key is _UNSET:
        from pyplus.config import settings

        secret_key = settings.secret_key
    if not secret_key:
        return None
    msg = f"ical:{user_id}".encode()
    digest = hmac.new(secret_key.encode(), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode().rstrip("=")


def verify_ical_token(token: str, user_id: int, secret_key: str | None = _UNSET) -> bool:  # type: ignore[assignment]
    """Constant-time verification.  Returns False if key is absent or token is wrong."""
    expected = make_ical_token(user_id, secret_key)
    if expected is None:
        return False
    return hmac.compare_digest(token, expected)
