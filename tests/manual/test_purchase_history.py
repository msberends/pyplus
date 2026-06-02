"""
Test get_purchase_history_api() — fetch all previously bought products.

Usage:
    python3 test_purchase_history.py ~/plus_credentials.yaml [--wide]

Options:
    --wide   Use from_date=2020-01-01 (all-time). Default: 2024-01-01.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from plus.client import PlusClient


async def main(creds_path: Path, from_date: str) -> None:
    creds = yaml.safe_load(creds_path.read_text())
    email = creds["email"]
    password = creds["password"]
    if isinstance(email, list):
        email = email[0]
    if isinstance(password, list):
        password = password[0]

    async with PlusClient(headless=True) as client:
        await client.login(email, password)
        await client.get_session_state()

        print(f"\n[*] Ophalen aankoopgeschiedenis vanaf {from_date}…\n")
        products = await client.get_purchase_history_api(from_date=from_date)

        print(f"\n[+] {len(products)} eerder gekochte producten gevonden\n")
        print(f"  {'SKU':<10} {'Merk':<20} {'Naam':<38} {'Prijs':>6}  Beschikbaar")
        print("  " + "-" * 82)
        for p in products:
            avail = "✓" if p.is_available else "✗"
            brand = (p.brand or "—")[:20]
            name = p.name[:38]
            print(f"  {p.sku:<10} {brand:<20} {name:<38} €{p.price:>5.2f}  {avail}")

        # Summary by category
        from collections import Counter

        cats = Counter(p.categories[0] if p.categories else "Onbekend" for p in products)
        print("\nCategorieën:")
        for cat, count in cats.most_common():
            print(f"  {count:>3}×  {cat}")


if __name__ == "__main__":
    args = sys.argv[1:]
    wide = "--wide" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    creds_path = Path(args[0])
    from_date = "2020-01-01" if wide else "2024-01-01"
    asyncio.run(main(creds_path, from_date))
