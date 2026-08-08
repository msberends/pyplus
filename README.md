# PyPLUS

[![version](https://img.shields.io/github/v/tag/msberends/pyplus?label=version&sort=semver)](https://github.com/msberends/pyplus/tags)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A personal, fast Dutch grocery-shopping web app for **PLUS.nl**. Plan the week's meals, keep your
recipes and fixed weekly products, and fill your real PLUS.nl cart in minutes — then press the final
*bestellen* on PLUS yourself.

> **The single goal:** get the routine weekly shop into the PLUS cart in **under 2 minutes** (under
> 10 on an unusual week). Every feature is judged against that. The app never completes checkout for
> you — you confirm payment and the delivery slot on plus.nl.

---

## What it does

- **Live cart** — the cart on screen *is* your real PLUS.nl cart, kept in sync optimistically on
  every add/remove and reconciled from PLUS's response.
- **Weekmenu** — a 7-dinner + 5-lunch weekly meal planner built from your own dishes, with a shuffle
  and one-tap "add the whole week" to cart.
- **Vaste boodschappen (staples)** — your fixed weekly products with replenishment timing; add or
  remove inline, or top up everything that's due in one tap.
- **Aanbiedingen (promotions)** — this week's PLUS deals, ranked by relevance to what you actually buy.
- **Zoeken** — instant product search for ad-hoc extras.
- **Autopilot** — generates a complete shopping plan for the week (weekmenu + staples + promo
  swaps + free-delivery top-up) in one pass, based on your rules and history. You review anything
  it's unsure about — out-of-stock **vervangingsproducten**, free-text **flexibele ingrediënten**,
  **optionele ingrediënten**, and money-saving **besparingsproducten** — then add the whole plan to
  your cart at once. Optional push notification (see below) when a plan is ready.
- **Dish manager** — recipes with assisted ingredient→SKU mapping, prep notes, amounts/pack sizes,
  and planning metadata (prep time, meat/diet type, vegetable count). Ingredients can be **optional**
  (offered at cart-add) or **flexible** (a free-text placeholder whose product you pick at cart-add).
- **Local product catalogue** — the full store catalogue is synced to SQLite, so search is instant
  with images/prices, and staples or dish ingredients the store no longer carries are flagged
  *"niet meer verkrijgbaar"*.
- **Pack optimisation** — two complementary, always-transparent savings:
  - *Cross-dish* — aggregates ingredients across the week and buys the fewest packs (e.g.
    *2 × 300 g chicken → 1 × 650 g pack, split at home*), previewed before anything hits the cart.
  - *Cart-wide* — spots when a product in your cart is cheaper per unit in another pack size
    (e.g. *2 × 250 g coffee → 1 × 500 g*) and offers a one-tap swap, per item or all at once.
- **Exports** — an iCal feed of the week's menu (with prep notes) you can subscribe to from your
  phone, plus a plain-text shopping list.
- **Local intelligence layer** *(off by default)* — week-menu recommender, staple replenishment
  prediction, and promotion matching. All local, explainable, **no LLM, no cloud AI**. Suggest-only;
  it never touches the cart unless you explicitly enable Autopilot.
- **ntfy push notifications** — optional alerts when products you regularly buy go on sale next week,
  and when an Autopilot plan is ready for review.
- **Home Assistant integration** — a HACS-installable custom integration exposing weekmenu, staples,
  and Autopilot as entities/services (see [below](#home-assistant-integration)).
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
`refresh_product_catalogue` (full store catalogue, weekly), `recompute_ml`, `refresh_weather`
(Open-Meteo forecast, no API key needed), `weekly_ntfy`, `autopilot_prepare`, and `full_preload` (runs
the PLUS-dependent jobs in dependency order). All jobs are idempotent and locked per (user, resource)
so an in-app run and a cron run never collide.

See [`crontab-scripts.sh`](crontab-scripts.sh) for ready-to-paste cron lines and the recommended
schedule.

> **Jobs that call PLUS need credentials without you present** — so they only run for users who
> enabled *"Onthoud mij"* (remember-me), which stores encrypted credentials. Users without it still
> work fine; their caches just warm on first open instead, and they get no ntfy alerts or Autopilot
> plans. `recompute_ml` and `refresh_weather` are the only jobs that need no PLUS credentials.

---

## Home Assistant integration

PyPLUS ships a [HACS](https://hacs.xyz/)-compatible custom integration at
[`custom_components/pyplus/`](custom_components/pyplus/), so your weekmenu, Autopilot status, and
staples count can show up as entities in Home Assistant, plus services to set weekmenu slots or
trigger Autopilot from an automation.

It isn't in the default HACS store — add this repo as a **custom repository** (HACS → Integrations →
⋮ → Custom repositories → this repo URL, category *Integration*), then install and configure it with
an API key generated under **Instellingen → API-toegang** in PyPLUS. Full entity/service reference:
[`custom_components/pyplus/README.md`](custom_components/pyplus/README.md).

---

## PLUS.nl API

PyPLUS talks to PLUS.nl's internal API from inside an authenticated browser session — there is no
public API. The reverse-engineered endpoint reference (authentication, request/response shapes,
version-hash handling, known constraints) lives in a dedicated doc, kept out of this README:
[api_documentation](https://github.com/msberends/pyplus/tree/main/api_documentation).

---

## Deployment

PyPLUS binds to localhost and expects a reverse proxy terminating TLS in front of it. NiceGUI uses
WebSockets, so the proxy **must** forward the `Upgrade`/`Connection` headers. Put PyPLUS on its own
(sub)domain — e.g. `pyplus.example.com` — and set that as the server/virtual-host name below, plus
`PYPLUS_BASE_URL` in `.env` so ntfy deep links point at the right host.

### nginx

```nginx
server {
    server_name pyplus.example.com;   # ← your (sub)domain

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";   # required for NiceGUI WebSockets
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Apache2

Requires `mod_proxy` and `mod_proxy_http`:

```bash
sudo a2enmod proxy proxy_http
```

```apache
<VirtualHost *:80>
    ServerName pyplus.example.com   # ← your (sub)domain

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8080/ upgrade=websocket   # required by NiceGUI, Apache ≥2.4.47
    ProxyPassReverse / http://127.0.0.1:8080/
</VirtualHost>
```

On Apache older than 2.4.47, replace `upgrade=websocket` with a `mod_proxy_wstunnel` + `mod_rewrite`
rule that reroutes `Upgrade: websocket` requests to a `ws://` backend instead.

Both examples assume TLS termination is added separately (e.g. Certbot managing the `:443` block) —
adapt to your setup.

Run it under systemd using [`pyplus.service.example`](pyplus.service.example) as a template (copy to
`pyplus.service`, fill in the real paths — the real `.service` is gitignored).

---

## Project layout

```
.
├── plus/                       # Reverse-engineered PLUS.nl client (Playwright) — reused, not rewritten
├── pyplus/                     # The application
│   ├── __main__.py             # entrypoint: page routes, iCal endpoint, scheduler lifecycle, ui.run()
│   ├── config.py                # env-based settings (pydantic-settings)
│   ├── api/                     # REST API backing the Home Assistant integration
│   ├── db/                      # SQLAlchemy ORM models, async engine, user-scoped repo helpers
│   ├── security/                 # Fernet credential encryption + HMAC iCal/API tokens
│   ├── session/                  # per-user PlusClient lifecycle + session manager
│   ├── services/                 # cart, dishes, autopilot, aggregate (pack-opt), savings, search, history, exports
│   ├── ml/                       # recommender, replenish, promo_match, artifacts (off by default)
│   ├── jobs/                     # job registry + CLI + APScheduler wiring
│   ├── ui/                       # theme, components, pages (login, weekmenu, autopilot, dishes, settings, …)
│   └── i18n.py                   # Dutch UI strings (single source)
├── custom_components/pyplus/   # HACS-compatible Home Assistant integration
├── api_documentation/          # Reverse-engineered PLUS.nl endpoint reference
├── migrations/                 # Alembic versions
├── tests/                      # pytest unit suite (offline)
│   └── manual/                 # live-API smoke scripts (need real credentials — not part of CI)
├── tools/screenshot.py         # visual QA: headless Playwright screenshots of every page
├── crontab-scripts.sh          # cron reference for the operator
└── pyproject.toml              # uv-managed
```

---

## Development

```bash
uv run pytest          # offline unit suite (aggregation, savings, catalogue, ML, exports, cart, ntfy)
uv run ruff check .    # lint
uv run ruff format .   # format
```

The scripts under `tests/manual/` exercise the real PLUS.nl API and need a credentials file
(`email`/`password` YAML); they are manual smoke tests, not run by the suite. Keep them free of
personal data.
