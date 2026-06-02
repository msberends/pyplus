"""
One-time migration: R .rds data → PyPLUS SQLite.

Usage:
    uv run python tools/migrate_rds.py \\
        --rds-dir /path/to/plus_data \\
        --email   your@plus.nl       \\
        [--user-id 1]                \\
        [--week-start 2026-06-02]    \\
        [--dry-run]

What is migrated:
  • dishes        (51 items → dishes table, instructions → prep_notes)
  • ingredients   (267 items → dish_ingredients; qty=0 → optional=True;
                   label set + no URL → flexible/"needs relink")
  • product SKUs  (from product_list.rds → ingredient_skus cache)
  • fixed_products (character vector; category headings skipped)
  • weekmenu      (named list → weekmenu table for the given week_start)

The email address is only used at runtime to locate the per-user .rds files;
it is NEVER written to any log, committed file, or database column in plain text.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3 as _sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_sku(url: str) -> str:
    """Extract numeric SKU from a PLUS product URL tail, e.g. '…-482943' → '482943'."""
    m = re.search(r"-(\d+)$", str(url).strip())
    return m.group(1) if m else ""


def _int_or_none(value) -> int | None:
    """Coerce an R numeric/NA cell to int or None."""
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


# R dish "meat" labels → PyPLUS meat_type tokens (see db.models.MEAT_TYPES).
_MEAT_MAP = {
    "vegetarisch": "vega",
    "kip": "kip",
    "rund": "rund",
    "varken": "varken",
    "vis": "vis",
    "gecombineerd": "gecombineerd",
}


def _map_meat(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return _MEAT_MAP.get(str(value).strip().lower())


def _week_start_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


_SLOT_MAP = {
    "Maandag": "ma",
    "Dinsdag": "di",
    "Woensdag": "wo",
    "Donderdag": "do",
    "Vrijdag": "vr",
    "Zaterdag": "za",
    "Zondag": "zo",
    "lunch1": "lunch1",
    "lunch2": "lunch2",
    "lunch3": "lunch3",
    "lunch4": "lunch4",
    "lunch5": "lunch5",
}


# ── R → staging SQLite ────────────────────────────────────────────────────────


def _dump_rds_to_sqlite(rds_dir: Path, email_slug: str, sqlite_path: Path) -> None:
    """
    Run Rscript to read all .rds files and write them to a staging SQLite.
    The email_slug is provided at runtime and never committed.
    """
    r_code = f"""
suppressPackageStartupMessages({{
  library(DBI)
  library(RSQLite)
}})
datadir <- {repr(str(rds_dir))}
slug     <- {repr(email_slug)}
db_path  <- {repr(str(sqlite_path))}

read_user <- function(name) {{
  f <- file.path(datadir, paste0(name, "-", slug, ".rds"))
  if (!file.exists(f)) stop(paste("File not found:", f))
  as.data.frame(readRDS(f))
}}

con <- dbConnect(SQLite(), db_path)

# dishes
dishes <- read_user("dishes")
dbWriteTable(con, "dishes", dishes, overwrite=TRUE)

# dish_ingredients
di <- read_user("dish_ingredients")
dbWriteTable(con, "dish_ingredients", di, overwrite=TRUE)

# weekmenu: named list -> data.frame
wm_raw  <- readRDS(file.path(datadir, paste0("weekmenu-", slug, ".rds")))
weekmenu <- data.frame(
  slot      = names(wm_raw),
  dish_name = unlist(wm_raw, use.names=FALSE),
  stringsAsFactors = FALSE
)
dbWriteTable(con, "weekmenu", weekmenu, overwrite=TRUE)

# fixed_products: character vector -> data.frame preserving order
fp_raw <- readRDS(file.path(datadir, paste0("fixed_products-", slug, ".rds")))
fixed  <- data.frame(
  url        = fp_raw,
  sort_order = seq_along(fp_raw) - 1L,
  stringsAsFactors = FALSE
)
dbWriteTable(con, "fixed_products", fixed, overwrite=TRUE)

# product_list (shared, no user suffix)
pl <- as.data.frame(readRDS(file.path(datadir, "product_list.rds")))
dbWriteTable(con, "product_list", pl, overwrite=TRUE)

dbDisconnect(con)
cat("OK\\n")
"""
    with tempfile.NamedTemporaryFile(suffix=".R", mode="w", delete=False) as fh:
        fh.write(r_code)
        script = Path(fh.name)

    try:
        r = subprocess.run(["Rscript", str(script)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"Rscript exited {r.returncode}:\n{r.stderr.strip()}")
    finally:
        script.unlink(missing_ok=True)


# ── Migration report ──────────────────────────────────────────────────────────


@dataclass
class MigrationReport:
    dishes_created: int = 0
    dishes_skipped: int = 0
    ingredients_created: int = 0
    ingredients_skipped: int = 0
    needs_relink: list = field(default_factory=list)  # [(dish_name, description)]
    fixed_created: int = 0
    fixed_skipped: int = 0
    fixed_headings_skipped: int = 0
    weekmenu_filled: int = 0
    weekmenu_missed: list = field(default_factory=list)  # dish names not found

    def print(self) -> None:
        print("\n════════════════════════════════════════════════════")
        print("  PyPLUS migratierapport")
        print("════════════════════════════════════════════════════")
        print(f"  Gerechten   : {self.dishes_created} nieuw, {self.dishes_skipped} al aanwezig")
        print(
            f"  Ingrediënten: {self.ingredients_created} geïmporteerd, {self.ingredients_skipped} overgeslagen"
        )
        print(
            f"  Vaste art.  : {self.fixed_created} geïmporteerd, {self.fixed_skipped} al aanwezig"
        )
        print(f"               ({self.fixed_headings_skipped} categoriekoppen genegeerd)")
        print(f"  Weekmenu    : {self.weekmenu_filled} slots gevuld")

        if self.needs_relink:
            print(f"\n  ⚠  {len(self.needs_relink)} ingrediënt(en) hebben geen product-SKU")
            print(
                "     (flexibele ingrediënten uit de R-app — herlink ze in de Gerechten-editor):\n"
            )
            for dish, desc in self.needs_relink:
                print(f"     • {dish}: {desc}")

        if self.weekmenu_missed:
            print(f"\n  ⚠  {len(self.weekmenu_missed)} weekmenu-slot(s) niet gevuld")
            print("     (gerechtnaam niet gevonden in geïmporteerde gerechten):\n")
            for slot, name in self.weekmenu_missed:
                print(f"     • {slot}: “{name}”")

        print("\n════════════════════════════════════════════════════\n")


# ── Core async migration ───────────────────────────────────────────────────────


async def _run_migration(
    staging: Path,
    user_id: int,
    week_start: date,
    dry_run: bool,
) -> MigrationReport:
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent))

    from sqlalchemy import select

    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.db.models import FixedProduct, Weekmenu

    report = MigrationReport()
    conn = _sqlite3.connect(staging)

    dishes_df = pd.read_sql("SELECT * FROM dishes", conn)
    di_df = pd.read_sql("SELECT * FROM dish_ingredients", conn)
    wm_df = pd.read_sql("SELECT * FROM weekmenu", conn)
    fp_df = pd.read_sql("SELECT * FROM fixed_products", conn)
    pl_df = pd.read_sql("SELECT * FROM product_list", conn)
    conn.close()

    # Build product lookup: url → row
    pl_df["sku"] = pl_df["url"].apply(_extract_sku)
    product_lookup: dict[str, pd.Series] = {row.url: row for row in pl_df.itertuples()}

    async with AsyncSessionLocal() as db:
        # ── 1. Dishes ──────────────────────────────────────────────────────────
        old_to_new: dict[int, int] = {}  # R dish_id → new DB dish.id
        dish_name_to_id: dict[str, int] = {}

        for _, drow in dishes_df.iterrows():
            old_id = int(drow["dish_id"])
            name = str(drow["name"]).strip()
            notes = str(drow.get("instructions", "") or "").strip()
            prep_minutes = _int_or_none(drow.get("preptime"))
            veg_count = _int_or_none(drow.get("vegetables"))
            meat_type = _map_meat(drow.get("meat"))

            if not dry_run:
                # Idempotency: skip if already exists
                from pyplus.db.models import Dish as _Dish

                existing = (
                    await db.execute(
                        select(_Dish).where(_Dish.user_id == user_id, _Dish.name == name)
                    )
                ).scalar_one_or_none()
                if existing:
                    old_to_new[old_id] = existing.id
                    dish_name_to_id[name] = existing.id
                    report.dishes_skipped += 1
                    continue

                dish = await repo.create_dish(
                    db,
                    user_id,
                    name=name,
                    prep_notes=notes,
                    prep_minutes=prep_minutes,
                    meat_type=meat_type,
                    veg_count=veg_count,
                )
                old_to_new[old_id] = dish.id
                dish_name_to_id[name] = dish.id
            else:
                # Dry-run: assign a synthetic id so ingredient mapping works
                old_to_new[old_id] = -(old_id)  # negative = synthetic
                dish_name_to_id[name] = -(old_id)
            report.dishes_created += 1

        # ── 2. Ingredients ─────────────────────────────────────────────────────
        sort_counters: dict[int, int] = {}  # new_dish_id → next sort_order

        for _, irow in di_df.iterrows():
            old_dish_id = int(irow["dish_id"])
            new_dish_id = old_to_new.get(old_dish_id)
            if new_dish_id is None:
                report.ingredients_skipped += 1
                continue

            sort_idx = sort_counters.get(new_dish_id, 0)
            sort_counters[new_dish_id] = sort_idx + 1

            product_url = irow.get("product_url")
            label = irow.get("label")
            qty = irow.get("quantity", 1)
            is_na_url = pd.isna(product_url)
            is_optional = (not is_na_url) and (qty == 0)
            is_flexible = is_na_url  # has label text but no SKU

            if is_flexible:
                # Flexible ingredient: no SKU, just an instruction label
                desc = str(label).strip() if not pd.isna(label) else "Onbekend ingrediënt"
                dish_name = dishes_df.loc[dishes_df["dish_id"] == old_dish_id, "name"].iloc[0]
                report.needs_relink.append((dish_name, desc))
                sku = ""
                display_name = desc
                prod_image = ""
            else:
                sku = _extract_sku(str(product_url))
                prod = product_lookup.get(str(product_url))
                display_name = str(prod.name) if prod else f"Product {sku}"
                prod_image = str(prod.img) if prod and not pd.isna(prod.img) else ""
                prod_unit = str(prod.unit) if prod and not pd.isna(prod.unit) else ""

                if sku and not dry_run:
                    # Warm the ingredient_skus cache
                    await repo.upsert_ingredient_sku(
                        db,
                        user_id,
                        sku,
                        name=display_name,
                        subtitle=prod_unit,
                        image_url=prod_image,
                    )

            amount = max(1, int(qty)) if not is_optional else 1

            if not dry_run:
                await repo.add_ingredient(
                    db,
                    new_dish_id,
                    sku=sku,
                    display_name=display_name,
                    amount=float(amount),
                    amount_unit="stuks",
                    optional=bool(is_optional),
                    flexible=bool(is_flexible),
                    sort_order=sort_idx,
                )
            report.ingredients_created += 1

        # ── 3. Fixed products ──────────────────────────────────────────────────
        fixed_sort = 0
        for _, frow in fp_df.sort_values("sort_order").iterrows():
            url = str(frow["url"]).strip()

            if not url.startswith("/product/"):
                report.fixed_headings_skipped += 1
                continue

            sku = _extract_sku(url)
            prod = product_lookup.get(url)
            name = str(prod.name) if prod else f"Product {sku}"

            if not sku:
                continue

            # Idempotency
            if not dry_run:
                existing_fp = (
                    await db.execute(
                        select(FixedProduct).where(
                            FixedProduct.user_id == user_id,
                            FixedProduct.sku == sku,
                        )
                    )
                ).scalar_one_or_none()
                if existing_fp:
                    report.fixed_skipped += 1
                    continue

            if not dry_run:
                db.add(
                    FixedProduct(
                        user_id=user_id,
                        sku=sku,
                        display_name=name,
                        default_qty=1,
                        sort_order=fixed_sort,
                    )
                )
            fixed_sort += 1
            report.fixed_created += 1

        # ── 4. Weekmenu ────────────────────────────────────────────────────────
        for _, wmrow in wm_df.iterrows():
            slot_r = str(wmrow["slot"]).strip()
            dish_name = str(wmrow["dish_name"]).strip()
            slot = _SLOT_MAP.get(slot_r)

            if not slot or not dish_name:
                continue

            new_dish_id = dish_name_to_id.get(dish_name)
            if not new_dish_id:
                report.weekmenu_missed.append((slot_r, dish_name))
                continue

            # Idempotency: skip if (user_id, slot, week_start) already exists
            already = False
            if not dry_run:
                existing_wm = (
                    await db.execute(
                        select(Weekmenu).where(
                            Weekmenu.user_id == user_id,
                            Weekmenu.slot == slot,
                            Weekmenu.week_start == week_start,
                        )
                    )
                ).scalar_one_or_none()
                already = existing_wm is not None

            if not already and not dry_run:
                db.add(
                    Weekmenu(
                        user_id=user_id,
                        slot=slot,
                        dish_id=new_dish_id,
                        week_start=week_start,
                    )
                )
            report.weekmenu_filled += 1

        if not dry_run:
            await db.commit()

    return report


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Migrate R .rds data → PyPLUS SQLite (one-time, idempotent)."
    )
    p.add_argument(
        "--rds-dir", required=True, type=Path, help="Directory containing the .rds files"
    )
    p.add_argument(
        "--email", required=True, help="Your PLUS.nl email (used only to locate per-user files)"
    )
    p.add_argument(
        "--user-id", type=int, default=None, help="PyPLUS user ID (defaults to first user in DB)"
    )
    p.add_argument(
        "--week-start",
        type=date.fromisoformat,
        default=None,
        help="Monday of the week to import weekmenu into (default: current week)",
    )
    p.add_argument("--dry-run", action="store_true", help="Print report without writing to DB")
    return p.parse_args()


async def _resolve_user_id(user_id_arg: int | None, dry_run: bool) -> int:
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent))

    if user_id_arg is not None:
        print(f"[migration] Using user_id={user_id_arg} (from --user-id)")
        return user_id_arg

    from sqlalchemy import select

    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.db.models import User

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is None:
            if dry_run:
                print("[migration] No users in DB — using user_id=1 for dry-run preview.")
                return 1
            raise SystemExit(
                "No users found in DB.\n"
                "Log in to the app at http://127.0.0.1:8080 first to create your user record,\n"
                "then re-run this migration."
            )
        print(f"[migration] Using user_id={user.id} (display_name={user.display_name!r})")
        return user.id


def main() -> None:
    args = _parse_args()

    rds_dir = args.rds_dir.expanduser().resolve()
    if not rds_dir.is_dir():
        sys.exit(f"Error: --rds-dir {rds_dir} does not exist.")

    # Derive the email slug (make.names equivalent: replace @ and . with .)
    import re as _re

    email_slug = _re.sub(r"[^A-Za-z0-9]", ".", args.email.strip())
    # Verify file exists
    test_file = rds_dir / f"dishes-{email_slug}.rds"
    if not test_file.exists():
        sys.exit(
            f"Error: {test_file} not found.\n"
            f"Check --rds-dir and --email. R uses make.names() to sanitise the email."
        )

    week_start = args.week_start or _week_start_for(date.today())
    print(f"[migration] week_start = {week_start}  (--week-start YYYY-MM-DD to override)")

    if args.dry_run:
        print("[migration] DRY RUN — nothing will be written to DB")

    user_id = asyncio.run(_resolve_user_id(args.user_id, args.dry_run))

    # Dump .rds → staging SQLite
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as fh:
        staging = Path(fh.name)

    try:
        print("[migration] Running Rscript to export .rds → staging SQLite…")
        _dump_rds_to_sqlite(rds_dir, email_slug, staging)
        print("[migration] Rscript done. Importing into PyPLUS DB…")

        report = asyncio.run(_run_migration(staging, user_id, week_start, args.dry_run))
    finally:
        staging.unlink(missing_ok=True)

    report.print()

    if report.needs_relink:
        print(
            "  Herlink de bovenstaande ingrediënten via:\n"
            "  Gerechten → [gerecht] → Bewerk → [ingrediënt] → 🔗 Verander product\n"
        )

    if not args.dry_run:
        print("  Migratie voltooid.\n")
    else:
        print("  Dry run voltooid — geen wijzigingen aangebracht.\n")


if __name__ == "__main__":
    main()
