"""
MVP pipeline test for PLUS.nl integration.

Usage:
    python test_pipeline.py path/to/credentials.yaml [--trace] [--screenshots]

Tests login + multi-item basket add via hybrid approach:
  - Item 1: browser click (captures ActionCheckoutItem_Add apiVersion)
  - Items 2-N: direct API call (~300ms each, no browser navigation)
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

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"

# Test basket: (sku, quantity)  — SKU = trailing number in PLUS product URL
BASKET: list[tuple[str, int]] = [
    ("415809", 1),  # 11er knapperige rösti 500g
    ("144366", 1),  # 3G BBQ en oven spray 500ml
    ("838535", 2),  # 7UP Zero Sugar 1500ml
    ("218417", 1),  # Anta Refresh eucalyptus 72g
    ("218419", 1),  # Anta Refresh sinaasappel 72g
    ("180275", 3),  # Aardappel Anders bacon-ui 464g
    ("180280", 1),  # Aardappel Anders ham-kaas 466g
    ("180285", 1),  # Aardappel Anders kruiden-knoflook 474g
    ("779260", 2),  # Aarts asperges gesneden 280g
    ("744909", 1),  # Aarts fruitcocktail light 340g
]


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


async def run(creds_path: Path, trace: bool, screenshots: bool) -> None:
    if screenshots:
        SCREENSHOT_DIR.mkdir(exist_ok=True)

    total_qty = sum(q for _, q in BASKET)
    print("=" * 62)
    print("PyPLUS MVP — multi-item basket test")
    print("=" * 62)
    print(f"Credentials : {creds_path}")
    print(f"Basket      : {len(BASKET)} producten, {total_qty} stuks totaal")
    print(f"Trace       : {'trace.zip' if trace else 'nee'}")
    print(f"Screenshots : {'ja' if screenshots else 'nee'}")
    print("=" * 62)

    email, password = load_credentials(creds_path)

    async def screenshot(name: str) -> None:
        if screenshots:
            path = SCREENSHOT_DIR / f"{name}.png"
            await client._page.screenshot(path=str(path), full_page=True)

    async with PlusClient(headless=True) as client:
        if trace:
            await client._context.tracing.start(screenshots=True, snapshots=True, sources=True)

        # ── Step 1: Login ─────────────────────────────────────────────
        print("\n[1/4] Inloggen bij PLUS.nl…")
        ok = await client.login(email, password)
        await screenshot("01_login")
        if not ok:
            print("\n[FAIL] Login mislukt.")
            sys.exit(1)

        # ── Step 2: Session state ─────────────────────────────────────
        print("\n[2/4] Sessiegegevens ophalen…")
        state = await client.get_session_state()

        # ── Step 3: Cart before ───────────────────────────────────────
        print("\n[3/4] Winkelwagen voor toevoeging…")
        cart_before = await client.get_cart()
        qty_before = sum(i.quantity for i in cart_before.items)
        print(f"      {len(cart_before.items)} producten, {qty_before} stuks")
        await screenshot("03_cart_before")

        # ── Step 4: Add basket ────────────────────────────────────────
        print(f"\n[4/4] Mandje toevoegen ({len(BASKET)} producten)…")
        print(f"      {'SKU':<10}  {'qty':>3}  {'methode':<8}  {'tijd':>8}  product")
        print(f"      {'-' * 10}  {'---':>3}  {'-' * 8}  {'--------':>8}  -------")

        timings_browser: list[float] = []
        timings_api: list[float] = []
        last_checkout = None

        for i, (sku, qty) in enumerate(BASKET):
            if i == 0:
                # First item via browser — captures ActionCheckoutItem_Add apiVersion
                t0 = time.perf_counter()
                await client.add_to_cart(sku, quantity=qty)
                elapsed = time.perf_counter() - t0
                timings_browser.append(elapsed)
                method = "browser"
                time_str = f"{elapsed:.1f}s"
            else:
                # All subsequent items via direct API
                t0 = time.perf_counter()
                last_checkout = await client.add_to_cart_api(sku, quantity=qty)
                elapsed = time.perf_counter() - t0
                timings_api.append(elapsed)
                method = "API"
                time_str = f"{elapsed * 1000:.0f}ms"

            product_name = ""
            if last_checkout:
                for line in last_checkout.get("LineItemList", {}).get("List", []):
                    if line.get("SKU") == sku:
                        product_name = line.get("Name", "")
                        break

            print(f"      {sku:<10}  {qty:>3}  {method:<8}  {time_str:>8}  {product_name}")

        await screenshot("04_after_basket")

        # ── Summary ───────────────────────────────────────────────────
        print()
        if last_checkout:
            cart_final = PlusDirectClient(state).cart_from_checkout(last_checkout)
            print(cart_final)
        else:
            cart_final = await client.get_cart()
            print(cart_final)

        print()
        qty_added = sum(q for _, q in BASKET)
        avg_api_ms = (sum(timings_api) / len(timings_api) * 1000) if timings_api else 0
        total_time = sum(timings_browser) + sum(timings_api)

        print(f"Toegevoegd  : {qty_added} stuks over {len(BASKET)} producten")
        print(f"Browser     : {timings_browser[0]:.1f}s (item 1, incl. apiVersion capture)")
        if timings_api:
            print(f"Directe API : gem. {avg_api_ms:.0f}ms per item ({len(timings_api)} items)")
        print(f"Totale tijd : {total_time:.1f}s")
        equiv_browser = timings_browser[0] * len(BASKET)
        print(f"Geschat R   : ~{equiv_browser * 6:.0f}s (6× browser-tijd per item)")
        print(f"Winst       : {equiv_browser * 6 / total_time:.0f}× sneller")

        if trace:
            await client._context.tracing.stop(path="trace.zip")
            print("\nTrace: playwright show-trace trace.zip --host 0.0.0.0 --port 9323")


def main() -> None:
    args = sys.argv[1:]
    trace = "--trace" in args
    screenshots = "--screenshots" in args
    args = [a for a in args if not a.startswith("--")]

    if not args:
        print(__doc__)
        sys.exit(1)

    creds_path = Path(args[0])
    if not creds_path.exists():
        print(f"[FOUT] Credentials bestand niet gevonden: {creds_path}")
        sys.exit(1)

    asyncio.run(run(creds_path, trace=trace, screenshots=screenshots))


if __name__ == "__main__":
    main()
