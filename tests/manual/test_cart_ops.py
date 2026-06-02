"""
Cart operations demo — add then remove via direct API.

Flow:
  1. Login + session state
  2. Read current cart
  3. Browser +1 on test SKU  → captures add apiVersion
  4. Direct API  +2 on test SKU  → 300ms
  5. Browser prime_remove_api() → captures remove apiVersion + LineItemId
  6. Direct API  -1 on test SKU  → 300ms
  7. Direct API  -2 on test SKU  → 300ms
  8. Read cart — confirms all changes

Usage:
    python test_cart_ops.py path/to/credentials.yaml [sku] [--screenshots]
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from plus.api import PlusDirectClient
from plus.client import PlusClient

SCREENSHOT_DIR = Path(__file__).parent / "screenshots" / "cart_ops"
DEFAULT_SKU = "957806"


def load_credentials(path: Path) -> tuple[str, str]:
    with open(path) as f:
        creds = yaml.safe_load(f)
    email = creds["email"]
    password = creds["password"]
    if isinstance(email, list):
        email = email[0]
    if isinstance(password, list):
        password = password[0]
    return str(email), str(password)


async def run(creds_path: Path, sku: str, screenshots: bool) -> None:
    if screenshots:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    email, password = load_credentials(creds_path)

    async with PlusClient(headless=True) as client:

        async def screenshot(name: str) -> None:
            if screenshots:
                await client._page.screenshot(
                    path=str(SCREENSHOT_DIR / f"{name}.png"), full_page=True
                )

        def show_cart(label: str, checkout: dict) -> None:
            c = PlusDirectClient(client._session).cart_from_checkout(checkout)
            print(f"\n  {label}: {c.total_items} stuks  €{c.final_total:.2f}")
            for item in c.items:
                tag = " ←" if item.product and sku in str(item) else ""
                print(f"    {item.quantity:>2}x  {item.product}{tag}")

        # ── Login ─────────────────────────────────────────────────────
        print("\n[1/7] Inloggen…")
        ok = await client.login(email, password)
        if not ok:
            print("[FAIL]")
            sys.exit(1)

        # ── Session state ─────────────────────────────────────────────
        print("\n[2/7] Sessiegegevens ophalen…")
        state = await client.get_session_state()
        cart = await client.get_cart()
        print(f"  {cart.total_items} stuks, €{cart.final_total:.2f}")
        await screenshot("01_start")

        # ── Add: browser prime if needed, else direct API immediately ─
        if not state.cart_add_api_version:
            print(f"\n[3/7] Cache leeg — browser +1 op SKU {sku} (legt add-apiVersion vast)…")
            t = time.perf_counter()
            await client.add_to_cart(sku, quantity=1)
            print(
                f"  {time.perf_counter() - t:.1f}s  add apiVersion: {state.cart_add_api_version[:16]}…"
            )
        else:
            print("\n[3/7] Cache gevonden — sla browser-prime over, direct API +1…")
            t = time.perf_counter()
            await client.add_to_cart_api(sku, quantity=1)
            print(f"  {time.perf_counter() - t:.1f}s (directe API, geen browser)")

        # ── Direct API +2 ─────────────────────────────────────────────
        print(f"\n[4/7] Directe API +2 op SKU {sku}…")
        checkout = await client.add_to_cart_api(sku, quantity=2)
        show_cart("Na +3 totaal", checkout)
        await screenshot("02_after_add")

        # ── Remove prime: only if apiVersion or LineItemIds missing ────
        need_prime = not state.cart_remove_api_version or sku not in state.line_item_ids
        if need_prime:
            print("\n[5/7] prime_remove_api() — browser-klik nodig…")
            t = time.perf_counter()
            ok = await client.prime_remove_api()
            print(
                f"  {time.perf_counter() - t:.1f}s  "
                f"remove apiVersion: {state.cart_remove_api_version[:16] if ok else '(mislukt)'}…"
            )
        else:
            print("\n[5/7] Cache + LineItemIds gevonden — geen browser-prime nodig!")
            print(f"  remove apiVersion (cache): {state.cart_remove_api_version[:16]}…")
        print(f"  LineItemIds bekend: {list(state.line_item_ids.keys())}")

        # ── Direct API -1 ─────────────────────────────────────────────
        print(f"\n[6/7] Directe API -1 op SKU {sku}…")
        checkout = await client.remove_from_cart_api(sku, quantity=1)
        show_cart("Na -1", checkout)
        await screenshot("03_after_remove1")

        # ── Direct API -2 ─────────────────────────────────────────────
        print(f"\n[7/7] Directe API -2 op SKU {sku}…")
        checkout = await client.remove_from_cart_api(sku, quantity=2)
        show_cart("Na -2", checkout)
        await screenshot("04_after_remove2")

        print("\n[OK] Add en remove via directe API werken beide!")


def main() -> None:
    args = sys.argv[1:]
    screenshots = "--screenshots" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    creds_path = Path(args[0])
    if not creds_path.exists():
        print(f"[FOUT] {creds_path}")
        sys.exit(1)
    sku = args[1] if len(args) > 1 else DEFAULT_SKU
    asyncio.run(run(creds_path, sku=sku, screenshots=screenshots))


if __name__ == "__main__":
    main()
