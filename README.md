# PyPLUS

A personal, fast Dutch grocery-shopping web app for **PLUS.nl**. Plan the week's meals, keep your
recipes and fixed weekly products, and fill your real PLUS.nl cart in minutes — then press the final
*bestellen* on PLUS yourself.

PyPLUS replaces an older R/Shiny app. Its PLUS.nl integration talks to the supermarket's internal
OutSystems API directly (≈400 ms per cart operation instead of the 20–30 s the old browser-driven
version needed). See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how that API was reverse-engineered, and
[`SONNET_BUILD_INSTRUCTION.md`](SONNET_BUILD_INSTRUCTION.md) for the full product/design specification.

> **The single goal:** get the routine weekly shop into the PLUS cart in **under 2 minutes** (under
> 10 on an unusual week). Every feature is judged against that. The app never completes checkout for
> you — you confirm payment and the delivery slot on plus.nl.

---

## What it does

- **Single-surface cockpit** — four item *sources* (lanes) feed one **live cart** (the cart on screen
  *is* your real PLUS cart, kept in sync optimistically):
  1. **Deze week** — a 7-dinner + 5-lunch weekly meal planner built from your dishes.
  2. **Vaste boodschappen** — your fixed weekly staples.
  3. **Aanbiedingen voor jou** — this week's promotions, ranked for relevance.
  4. **Zoeken** — instant product search for ad-hoc extras.
- **Dish manager** — recipes with strict, assisted ingredient→SKU mapping, prep notes, amounts/pack
  sizes, optional-ingredient flags, and one-tap relinking when a product changes.
- **Cross-dish pack optimization** — aggregates ingredients across the week and picks the cheapest
  pack combination (e.g. *2 × 300 g chicken → 1 × 650 g pack, split at home*), shown transparently
  before anything hits the cart.
- **Exports** — an iCal feed of the week's menu (with prep notes) you can subscribe to from your
  phone, plus a plain-text shopping list.
- **Local intelligence layer** *(off by default)* — week-menu recommender, staple replenishment
  prediction, and promotion matching. All local, explainable, **no LLM, no cloud AI**. Suggest-only;
  it never touches the cart unless you explicitly enable Autopilot.
- **ntfy weekly alert** — an optional push when products you regularly buy go on sale next week.
- **Multi-user** — each PLUS account is an isolated session with its own cart and data.

UI language is **Dutch**; code and comments are English.

---

## Quick start

Requirements: **Python 3.11+** and [**uv**](https://docs.astral.sh/uv/).

```bash
# 1. Install dependencies (creates .venv from pyproject + uv.lock)
uv sync

# 2. Install the headless browser PyPLUS uses to talk to PLUS.nl
uv run playwright install chromium
uv run playwright install-deps chromium   # system libs; needs root on a minimal server

# 3. Configure
cp .env.example .env
#    Generate an encryption key and put it in .env as PYPLUS_SECRET_KEY:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 4. Run
uv run python -m pyplus
```

The app serves at `http://127.0.0.1:8080` by default. Open it, log in with your PLUS.nl account, and
confirm your store on first login.

The SQLite database and Alembic migrations are created automatically on first start; no manual
migration step is needed for a fresh install.

---

## Configuration

All settings are environment variables (prefix `PYPLUS_`), read from `.env`. See
[`.env.example`](.env.example) for the documented template.

| Variable | Default | Purpose |
|---|---|---|
| `PYPLUS_SECRET_KEY` | *(empty)* | Fernet key for encrypting stored credentials at rest. **Absent ⇒ remember-me and background jobs are disabled** (fail safe). Generate with the snippet above. |
| `PYPLUS_HOST` | `127.0.0.1` | Bind address (sit behind a reverse proxy). |
| `PYPLUS_PORT` | `8080` | Bind port. |
| `PYPLUS_DATA_DIR` | `~/.local/share/pyplus` | Where the SQLite DB, ML artifacts, and logs live. |
| `PYPLUS_DISABLE_SCHEDULER` | `0` | Set to `1` to disable the in-app scheduler and rely on cron only. |
| `PYPLUS_NTFY_URL` | `https://ntfy.sh` | Default ntfy instance (overridable per user in Settings). |
| `PYPLUS_BASE_URL` | *(empty)* | Public URL of the app, used in ntfy deep links. Empty ⇒ no deep links. |

---

## Background jobs & caching

**The app opens fast because nothing on the open path calls PLUS except login + the live-cart fetch.**
Promotions, purchase/order history, product facts, and ML suggestions all render from precomputed
SQLite caches, then revalidate quietly. Those caches are warmed by background jobs.

Every job is a plain function runnable two ways:

- **In-app** via APScheduler (registered automatically at startup unless `PYPLUS_DISABLE_SCHEDULER=1`).
- **From cron / the shell** via the CLI:
  ```bash
  uv run python -m pyplus.jobs <name> [--user all|<id>]
  ```

Named jobs: `refresh_orders`, `refresh_purchase_catalogue`, `refresh_promotions`, `refresh_products`,
`recompute_ml`, `weekly_ntfy`, and `full_preload` (runs them in dependency order). The two paths are
idempotent and locked per (user, resource) so an in-app run and a cron run never collide.

See [`crontab-scripts.sh`](crontab-scripts.sh) for ready-to-paste cron lines and the recommended
schedule.

> **Jobs that call PLUS need credentials without you present** — so they only run for users who
> enabled *"Onthoud mij"* (remember-me), which stores encrypted credentials. Users without it still
> work fine; their caches just warm on first open instead, and they get no ntfy alerts. `recompute_ml`
> is the only job that needs no credentials.

---

## Deployment

PyPLUS binds to localhost and expects a reverse proxy (nginx/Caddy) terminating TLS in front of it.
NiceGUI uses WebSockets, so the proxy **must** forward the `Upgrade`/`Connection` headers:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";   # required for NiceGUI WebSockets
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

Run it under systemd using [`pyplus.service.example`](pyplus.service.example) as a template (copy to
`pyplus.service`, fill in the real paths — the real `.service` is gitignored).

---

## Security & GitHub hygiene

This repository is public. The rules it follows:

- **No personal data is committed** — no real emails, domains, credentials, or server paths anywhere
  in code, docs, fixtures, or commit messages. Placeholders only (`you@example.com`, `<APP_DIR>`).
- **Credentials at rest are Fernet-encrypted** with `PYPLUS_SECRET_KEY`, which the operator sets and
  which is never committed or defaulted. No key ⇒ remember-me is disabled, not bypassed.
- **Multi-user isolation** — every DB query is scoped by `user_id`; each session has its own browser
  context and PLUS cart. Users can never see or affect each other's data.
- **`.gitignore` keeps secrets and data out of the repo:** `.env`, `*.service`, the data dir,
  `*.db`, `logs/`, the apiVersion cache, ML artifacts, and the operator's personal
  `NOTES_FOR_ADMIN.md`.

---

## Project layout

```
new_app/
├── plus/              # Reverse-engineered PLUS.nl client (see ARCHITECTURE.md) — reused, not rewritten
├── pyplus/            # The application
│   ├── __main__.py    # entrypoint: page routes, iCal endpoint, scheduler lifecycle, ui.run()
│   ├── config.py      # env-based settings (pydantic-settings)
│   ├── db/            # SQLAlchemy ORM models, async engine, user-scoped repo helpers
│   ├── security/      # Fernet credential encryption + HMAC iCal tokens
│   ├── session/       # per-user PlusClient lifecycle + session manager
│   ├── services/      # cart, dishes, aggregate (pack-opt), history, exports
│   ├── ml/            # recommender, replenish, promo_match, artifacts (off by default)
│   ├── jobs/          # job registry + CLI + APScheduler wiring
│   ├── ui/            # theme, components, pages (login, cockpit, dishes, settings)
│   └── i18n.py        # Dutch UI strings (single source)
├── migrations/        # Alembic versions
├── tools/migrate_rds.py   # one-time R .rds → SQLite importer
├── tests/             # pytest unit suite (offline)
│   └── manual/        # live-API smoke scripts (need real credentials — not part of CI)
├── crontab-scripts.sh # cron reference for the operator
└── pyproject.toml     # uv-managed; requirements.txt covers only the manual client scripts
```

---

## Development

```bash
uv run pytest          # offline unit suite (aggregation, ML, exports, cart, ntfy)
uv run ruff check .    # lint
uv run ruff format .   # format
```

The scripts under `tests/manual/` exercise the real PLUS.nl API and need a credentials file
(`email`/`password` YAML); they are manual smoke tests, not run by the suite. Keep them free of
personal data.
