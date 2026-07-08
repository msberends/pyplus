# CLAUDE.md — PyPLUS

Guidance for working in this repository. Read `README.md` for the user-facing overview,
`ARCHITECTURE.md` for the PLUS.nl integration internals, and `SONNET_BUILD_INSTRUCTION.md` for the
authoritative product/design spec (it leaves few decisions open — follow it where it speaks).

## What this is

A personal Dutch grocery-shopping web app for PLUS.nl. **The single goal governs all scope:** get the
routine weekly shop into the real PLUS cart in under ~2 minutes. If a change doesn't make the weekly
shop faster or the experience smoother, it probably doesn't belong.

- **UI:** NiceGUI (FastAPI + Vue/Quasar, async, WebSockets).
- **Data:** SQLite via SQLAlchemy 2.x ORM (async, aiosqlite), Alembic migrations.
- **PLUS integration:** the `plus/` package (Playwright). **Reuse it; do not rewrite it.**
- **ML:** scikit-learn/pandas/numpy — local, explainable, **no LLM ever**.

## Commands

```bash
uv sync                                   # install deps
uv run python -m pyplus                   # run the app (127.0.0.1:8080)
uv run python -m pyplus.jobs <name> [--user all|<id>]   # run a background job
uv run pytest                             # offline unit suite
uv run ruff check . && uv run ruff format .
```

Run `ruff` and `pytest` clean before declaring work done. `tests/manual/` hits the live PLUS API and
needs real credentials — it is **not** part of the suite; never put personal data in it.

## Screenshots

The app runs as a systemd service — never kill it or start it with nohup. To restart after code
changes, run `sudo service pyplus restart` (passwordless sudoers rule in place). For UI work, take
screenshots to verify changes visually.

**Tool:** `tools/screenshot.py` — headless Playwright, auto-login, session cached to
`.screenshot_session.json` (gitignored). Credentials and app URL come from `.screenshot.env`
(gitignored; never commit).

```bash
uv run python tools/screenshot.py                     # all pages (desktop 1400×900)
uv run python tools/screenshot.py weekmenu staples    # specific pages only
```

Output lands in `screenshots/` (gitignored). Pages: `login weekmenu promos staples cart dishes settings cockpit`.

**Mobile screenshots (560 px):** reuse the cached session with a custom script — the session file
stores cookies/storage so no re-login is needed as long as the session is fresh:

```python
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path("/var/www/pyplus")

def load_env():
    env = {}
    for line in (ROOT / ".screenshot.env").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env

async def main():
    env = load_env()
    base_url = env["APP_URL"].rstrip("/")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 560, "height": 900},
            storage_state=str(ROOT / ".screenshot_session.json"),
            locale="nl-NL",
        )
        page = await ctx.new_page()
        for name, path in [("mobile_weekmenu", "/weekmenu"), ("mobile_staples", "/staples")]:
            await page.goto(f"{base_url}{path}", wait_until="networkidle")
            await page.wait_for_timeout(2500)
            await page.screenshot(path=str(ROOT / f"screenshots/{name}.png"), full_page=True)
        await browser.close()

asyncio.run(main())
```

If the session is expired, run the desktop tool first (`uv run python tools/screenshot.py weekmenu`)
to trigger a fresh login and save the session.

**Assessing screenshots:** read the `.png` files with the Read tool — they are rendered visually.
Check: content visible (not blank/clipped), nav bar present, grids lay out correctly, no horizontal
overflow, text readable, bottom of page not obscured by the fixed nav bar.

## Layout (where things live)

- `plus/` — reverse-engineered PLUS client: `client.py` (all API methods + session capture),
  `api.py`, `models.py`, `version_cache.py`.
- `pyplus/config.py` — env settings (`PYPLUS_*`). `pyplus/__main__.py` — routes, iCal endpoint,
  scheduler lifecycle, `ui.run()`.
- `pyplus/db/` — `models.py` (all tables), `engine.py` (async session), `repo.py` (**user-scoped**
  data access).
- `pyplus/services/` — `cart.py`, `dishes.py`, `aggregate.py` (pack optimization), `history.py`
  (fuses PLUS history sources), `exports.py` (iCal + shopping list).
- `pyplus/ml/` — `interface.py` (the `PurchaseHistory` protocol every model reads),
  `recommender.py`, `replenish.py`, `promo_match.py`, `artifacts.py`.
- `pyplus/jobs/` — `registry.py` (job bodies), `__main__.py` (CLI), `preload.py` (APScheduler).
- `pyplus/ui/` — `theme.py` (design tokens/CSS), `components/`, `pages/`. `pyplus/i18n.py` — Dutch strings.
- `tools/migrate_rds.py` — one-time R `.rds` → SQLite importer.

## Hard invariants — do not violate

**PLUS integration (learned the hard way — see ARCHITECTURE.md):**
- All PLUS API calls go through `page.evaluate(fetch(...))` inside the logged-in browser context.
  Direct `httpx` returns **403**. Keep one Playwright context per active user session.
- Every cart write sends the latest `CheckoutVersion`; always update it from the response. Use the
  atomic `QuantityToAdd`/`QuantityToRemove` delta — never loop single adds.
- **Never hardcode a store number.** Each user has their own `store_number` (+ internal
  `user_store_id`), captured at login and stored on the `users` row. Examples in docs use store #720.
- apiVersion hashes are cached to disk and auto-rediscovered on `hasApiVersionChanged`. **Do not
  "simplify" the order/purchase-history payloads:** `viewName` must be exactly `AccountFlow.*` and the
  full `screenData.variables` must match the browser, or the server silently returns everything as
  unavailable (`Quantity=0`) with no error.

**Application behavior:**
- **The live cart IS the real PLUS cart.** There is no local staging basket. Add/remove call PLUS;
  update the UI optimistically, then reconcile from the authoritative response; revert + quiet inline
  error on failure.
- **Fast-open rule:** nothing on the open path may call PLUS except login + the live-cart fetch.
  Promotions, history, product facts, and ML suggestions all read from DB caches (warmed by jobs),
  rendered stale-but-present, then revalidated quietly. Never block first paint on a network call.
- **Background jobs** are both APScheduler tasks and CLI entrypoints sharing the same bodies; keep
  them idempotent and per-(user,resource) locked so cron and in-app runs never collide. Jobs that hit
  PLUS need stored remember-me credentials; skip users without them.
- **ML is off by default, suggest-only.** It is precomputed into `ml_artifacts` by `recompute_ml` —
  **never train, fetch history, or call PLUS on the request path.** Respect the dating gap:
  `ever_bought` (catalogue, incl. in-store, no dates) is distinct from `last_bought`/`frequency`
  (dated online orders only). Only Autopilot (explicit opt-in) may pre-fill the cart.
- **Multi-user isolation:** every DB query is scoped by `user_id`; validate the session's user on
  every action. Never share sessions or carts across users.
- **No checkout automation** — the user presses the final *bestellen* on plus.nl. (Other non-goals:
  no nutrition tracking, barcode scanning, social features, recipe import, dark mode, or
  next-week promotions in the UI.)

## Conventions

- **Dutch UI, English code.** All user-visible strings live in `pyplus/i18n.py`; code, comments, and
  identifiers are English.
- **Design:** own premium identity with PLUS green as accent (not a clone of plus.nl). Restrained
  motion — **no confetti, no cheerleading**; skeletons over spinners; quiet inline errors over modals.
  Build shared components in `ui/components/` and reuse them.
- **Security/privacy (public repo):** never commit personal emails, domains, credentials, or real
  server paths — placeholders only. Keep `.env`, `*.service`, the data dir, DBs, logs, the
  apiVersion cache, ML artifacts, and `NOTES_FOR_ADMIN.md` gitignored.
- **Migrations:** schema changes go through Alembic in `migrations/`; all tables are defined in
  `pyplus/db/models.py`.
