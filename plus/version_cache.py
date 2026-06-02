"""
Persistent cache for PLUS.nl OutSystems action-specific apiVersion hashes.

These values are baked into PLUS.nl's compiled JavaScript and are stable
between deployments. They only need to be (re)discovered when an API call
returns hasApiVersionChanged: true.

Default cache path: ~/.config/pyplus/api_versions.json
"""

from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PATH = Path.home() / ".config" / "pyplus" / "api_versions.json"

_KEYS = (
    "cart_add_api_version",
    "cart_remove_api_version",
    "cart_get_api_version",
    "cart_module_version",
    "cart_api_version",
    "promotions_api_version",
    "promo_detail_api_version",
    "purchase_history_api_version",
    "order_list_api_version",
    "order_detail_api_version",
    "search_api_version",
)


def load(path: Path = _DEFAULT_PATH) -> dict[str, str]:
    """Return cached versions dict, empty dict if not found."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(versions: dict[str, str], path: Path = _DEFAULT_PATH) -> None:
    """Write versions to disk, creating directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: v for k, v in versions.items() if k in _KEYS and v}, indent=2))
    print(f"[cache] API-versies opgeslagen: {path}")


def apply_to_session(session, path: Path = _DEFAULT_PATH) -> bool:
    """
    Load cached versions and apply to session state.
    Returns True if all required versions were found in cache.
    """
    cached = load(path)
    if not cached:
        return False
    for key, value in cached.items():
        if hasattr(session, key) and not getattr(session, key):
            setattr(session, key, value)
    found = bool(cached.get("cart_add_api_version") and cached.get("cart_remove_api_version"))
    if found:
        print(
            f"[cache] API-versies geladen uit cache (add: {cached.get('cart_add_api_version', '?')[:16]}…)"
        )
    return found


def save_from_session(session, path: Path = _DEFAULT_PATH) -> None:
    """Extract discovered versions from session and persist them."""
    save({k: getattr(session, k, "") for k in _KEYS}, path)
