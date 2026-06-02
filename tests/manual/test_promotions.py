"""
Test DataActionGetPromotionList_Optimization direct API call.

Usage:
    python test_promotions.py path/to/credentials.yaml [--next-week]
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from plus.client import PlusClient


def load_credentials(path: Path) -> tuple[str, str]:
    creds = yaml.safe_load(path.read_text())
    email, password = creds["email"], creds["password"]
    if isinstance(email, list):
        email = email[0]
    if isinstance(password, list):
        password = password[0]
    return str(email), str(password)


async def run(creds_path: Path, next_week: bool) -> None:
    email, password = load_credentials(creds_path)

    async with PlusClient(headless=True) as client:
        print(f"[1/3] Inloggen als {email}…")
        ok = await client.login(email, password)
        if not ok:
            print("[-] Login mislukt")
            sys.exit(1)

        print("[2/3] Sessiegegevens ophalen…")
        await client.get_session_state()
        print(
            f"      store_number={client._session.store_number}  "
            f"user_store_id={client._session.user_store_id}  "
            f"promotions_api_version={client._session.promotions_api_version[:16] or '(ontbreekt)'}…"
        )

        print(f"\n[3/3] Aanbiedingen ophalen ({'volgende week' if next_week else 'huidige week'})…")
        result = await client.get_promotions_api(next_week=next_week)

    print()
    print(result)
    print()

    total = len(result.promotions)
    single = sum(1 for p in result.promotions if p.is_single_product)
    free_del = sum(1 for p in result.promotions if p.is_free_delivery)
    print(f"Totaal     : {total} aanbiedingen")
    print(f"Enkelvoudig: {single} (met SKU)")
    print(f"Gratis bez.: {free_del}")

    # Save clean JSON for inspection
    out = Path(__file__).parent / "promotions_result.json"
    import dataclasses

    out.write_text(
        json.dumps(
            {
                "period_from": result.period_from,
                "period_to": result.period_to,
                "is_next_week_published": result.is_next_week_published,
                "promotions": [dataclasses.asdict(p) for p in result.promotions],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"\nJSON opgeslagen in {out}")


def main() -> None:
    args = sys.argv[1:]
    next_week = "--next-week" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    creds_path = Path(args[0])
    if not creds_path.exists():
        print(f"[FOUT] {creds_path} niet gevonden")
        sys.exit(1)
    asyncio.run(run(creds_path, next_week=next_week))


if __name__ == "__main__":
    main()
