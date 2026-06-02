# PyPLUS — Build Instruction for the Implementing Model

> **You are the implementing model (Claude Sonnet). This document is your complete brief.**
> It leaves no design decision open. Where you would normally ask "how should this look/behave?",
> the answer is here. If something is genuinely unspecified, choose the option that best serves
> the **single goal** (below) and the **two sacred principles** (below) — and document the choice.

---

## 0. Before you write any code

**The previous blocking dependency is resolved.** The PLUS.nl purchase-history and order-history
endpoints are reverse-engineered, implemented in `plus/client.py`, and documented in
`ARCHITECTURE.md` and Section 21 below. There is no longer a gate — you may build the full app,
including the intelligence layer, from the start.

First:
1. Read this whole document.
2. Read `new_app/ARCHITECTURE.md` (how the PLUS API was reverse-engineered — the cart & promotions
   pipeline already works).
3. Read `new_app/plan.md` (earlier loose plan — informative, not binding; this document supersedes it).
4. Read the existing working client in `new_app/plus/` (`client.py`, `api.py`, `models.py`,
   `version_cache.py`) and the test scripts. **Reuse this code. Do not rewrite it.**
5. Skim the R original in `R/pyplus.R` (~2900 lines) and `R/send_email.R` only to understand
   prior behaviour and the Dutch UI vocabulary. You are **not** porting R; you are building anew.

When ready, confirm your understanding and build in the milestone order of Section 19.

---

## 1. Mission

A personal Dutch grocery-shopping web app that gets the weekly shop done and on its way to the
user's doorstep (PLUS.nl delivers next day) **in under 10 minutes — ideally under 2 on a routine week.**

It replaces an older R/Shiny app. The PLUS.nl integration (login, live cart, promotions) is already
solved in Python and must be reused. You are building the full application around it: a beautiful,
fast, single-surface shopping cockpit with a live cart, a redesigned dish manager, smart pack
optimization, a local-ML intelligence layer, promotions integration, ntfy alerts, and exports.

### The single goal (the only thing that matters)
> Quickly do the weekly grocery shopping — add the user's own dishes and fixed weekly products to
> the PLUS cart with minimal effort — then the user presses the final "bestellen" on PLUS themselves.

Every feature is judged by one question: **does it make the routine weekly shop faster?** If it
doesn't, it is cut, deferred, or hidden behind an "advanced" affordance.

### The two sacred principles (never violate)
1. **UX must be very friendly; UI must be very, very good-looking and smooth.** Optimistic updates,
   sub-second feel, skeleton loaders, no full-page reloads, restrained tasteful motion.
2. **The single goal above governs all scope.**

---

## 2. Success criteria (definition of done)

- A returning user, on a routine week, can go from app-open to a complete PLUS cart in **under 2 minutes**; an unusual week in **under 10**.
- **App-open is fast:** the open path calls PLUS only for login + the live-cart fetch; every other lane (promotions, deals-for-you, staples-due, ML suggestions, product facts) paints from precomputed DB caches (§6.1/§13), then revalidates quietly. No lane blocks the first paint.
- The live cart on screen always equals the real PLUS.nl cart (optimistic, then reconciled).
- Existing R dish/ingredient/fixed-product/weekmenu data is imported intact on first run.
- Every dish ingredient resolves to a concrete, store-correct SKU; availability problems surface only where they actually occur (at add-to-cart) with substitute suggestions.
- Cross-dish ingredient quantities are aggregated and pack-optimized, with savings shown prominently.
- iCal export (weekmenu + prep notes) and plain-text shopping-list export both work.
- Multi-user: siblings reach it via reverse proxy, log in with only a PLUS account, and never see each other's data.
- No personal info (email, domain, credentials, user data) is ever committed to the GitHub repo.
- The ML layer is present, settings-driven, off by default, and never touches the cart unless the user opts in.

---

## 3. Product vision — the single-surface command center

The old R app was a 4-tab funnel (Weekmenu → Vaste boodschappen → Extra artikelen → Mandje →
PLUS Winkelwagen). That sequence existed only because the old API cost 20–30 s per item, forcing a
local staging basket pushed once at the end. **That constraint is gone** (~400 ms/item, optimistic
locking, no double-adds). So collapse the funnel.

**One primary screen — the Cockpit:** four item *sources* live side by side as lanes, all feeding a
**live cart pinned to the right** (the cart *is* the real PLUS cart). Secondary screens: Dish
Management, Settings, Login.

```
┌───────────────────────────────────────────────┬──────────────────┐
│  COCKPIT (stage)                               │   LIVE CART      │
│                                                │   (real PLUS     │
│  ① Deze week — meals (7 diners + 5 lunches)    │    cart)         │
│  ② Vaste boodschappen — staples (due-aware)    │                  │
│  ③ Aanbiedingen voor jou — deals               │   items, qty±,   │
│  ④ Zoeken — instant product search             │   images,        │
│                                                │   total, −€saved │
└───────────────────────────────────────────────┴──────────────────┘
```

This document specifies each piece in detail in Sections 9–14.

---

This file continues in sections below. The remaining sections are:

- **4.** Tech stack (2026)
- **5.** Project structure
- **6.** Data model (SQLite, multi-user, store-aware)
- **7.** PLUS integration layer (reuse + extend)
- **8.** The live cart
- **9.** Screens & IA in detail (Login, Cockpit lanes, Dish Management, Settings)
- **10.** Pack-optimization / cross-dish aggregation engine
- **11.** Intelligence layer (local ML)
- **12.** Promotions handling
- **13.** Background jobs, preloading & scheduled refresh (incl. ntfy + crontab)
- **14.** Exports (iCal + plain-text)
- **15.** Migration from R `.rds`
- **16.** Visual design system
- **17.** Security, secrets & GitHub hygiene
- **18.** Non-goals
- **19.** Build order / milestones
- **20.** Testing & acceptance
- **21.** RESOLVED: purchase & order history endpoints (reference)

---

## 4. Tech stack (2026)

| Concern | Choice | Notes |
|---|---|---|
| Language | **Python 3.13** | Match the existing client. |
| Dependency / project mgmt | **uv** (`pyproject.toml` + `uv.lock`) | Fast, reproducible, current-year default. No bare `requirements.txt` for the app (keep the existing one only for the legacy test scripts if needed). |
| UI framework | **NiceGUI** (latest) | FastAPI + Vue/Quasar, async-native, WebSocket reactivity, drag-drop, dialogs. Already chosen and validated in ARCHITECTURE.md. |
| PLUS integration | **Existing `plus/` package** (Playwright + `page.evaluate(fetch)`) | Reuse as-is; extend per Section 7. |
| Persistence | **SQLite** via **SQLAlchemy 2.x (ORM)** + **aiosqlite** (async engine) | One DB file under the gitignored data dir. ORM (not Core) for clarity given multiple related tables. |
| Migrations | **Alembic** | Versioned schema from day one. |
| Validation/models | **Pydantic v2** | Already used in `plus/models.py`. |
| Background jobs | **APScheduler** (AsyncIOScheduler) in-process **+ standalone CLI entrypoints** for system `crontab` | Every job is an importable function with a CLI entrypoint (`uv run python -m pyplus.jobs <name>`), runnable both by the in-app scheduler and by the operator's crontab. The operator has full freedom to schedule via cron (see §13 + `crontab-scripts.sh`). No external broker. |
| ML | **scikit-learn**, **pandas**, **numpy** | Lightweight, explainable, offline. **No LLM, ever.** |
| iCal | **icalendar** | |
| Secrets at rest | **cryptography (Fernet)** | Key from env var set by the server operator. |
| Password hashing (app remember-me token only) | not needed if we store encrypted PLUS creds; see §17 | |
| Lint/format | **ruff** (lint + format) | |
| Tests | **pytest** + **pytest-asyncio** | |
| Time/locale | Dutch locale for display (dates, currency `€`), `Europe/Amsterdam` tz | |

Run command: `uv run python -m pyplus` (single entrypoint), served behind the operator's reverse proxy. Bind host/port via env (`PYPLUS_HOST`, `PYPLUS_PORT`, default `127.0.0.1:8080`).

---

## 5. Project structure

```
new_app/
├── pyproject.toml            # uv-managed
├── uv.lock
├── .env.example              # documented, committed; real .env is gitignored
├── alembic.ini
├── migrations/               # Alembic versions
├── plus/                     # EXISTING — reuse; extend with product search + history (§7)
│   ├── client.py
│   ├── api.py
│   ├── models.py
│   └── version_cache.py
├── pyplus/
│   ├── __main__.py           # entrypoint: builds app, starts scheduler, ui.run()
│   ├── config.py             # env-based settings (pydantic-settings)
│   ├── db/
│   │   ├── engine.py         # async engine/session
│   │   ├── models.py         # SQLAlchemy ORM tables (§6)
│   │   └── repo.py           # data-access helpers, all user-scoped
│   ├── security/
│   │   └── secrets.py        # Fernet encrypt/decrypt of stored credentials
│   ├── session/
│   │   └── user_session.py   # per-logged-in-user PlusClient + SessionState lifecycle
│   ├── services/
│   │   ├── cart.py           # live cart ops + optimistic/reconcile
│   │   ├── ingredients.py    # ingredient↔SKU resolution, availability, relink
│   │   ├── aggregate.py      # cross-dish aggregation + pack optimization (§10)
│   │   ├── promotions.py     # deals-for-you matching + inline swap suggestions
│   │   ├── history.py        # purchase-history interface (§21) — single source for ML
│   │   ├── preload.py        # warms all caches + recomputes ML artifacts (§13)
│   │   ├── exports.py        # iCal + plain-text shopping list (§14)
│   │   └── ntfy.py           # push client
│   ├── ml/
│   │   ├── interface.py      # PurchaseHistory protocol consumed by all models
│   │   ├── recommender.py    # week-menu suggestions
│   │   ├── replenish.py      # staple due-prediction
│   │   ├── promo_match.py    # promo scoring vs history+menu
│   │   └── artifacts.py      # train/save/load precomputed model artifacts (§11/§13)
│   ├── jobs/
│   │   ├── __main__.py       # CLI: `python -m pyplus.jobs <name> [--user all|<id>]` (§13)
│   │   ├── registry.py       # named jobs: refresh_history, refresh_promotions,
│   │   │                     #   refresh_products, recompute_ml, weekly_ntfy, full_preload
│   │   ├── preload.py        # in-app APScheduler registration of the same jobs
│   │   └── weekly_ntfy.py    # the ntfy job body
│   ├── ui/
│   │   ├── theme.py          # design tokens / CSS (§16)
│   │   ├── components/       # cart panel, product card, qty stepper, dish card, etc.
│   │   └── pages/
│   │       ├── login.py
│   │       ├── cockpit.py    # the single-surface command center (§9.2)
│   │       ├── dishes.py     # dish management redo (§9.3)
│   │       └── settings.py   # incl. ML prefs, ntfy, store, account (§9.4)
│   └── i18n.py               # Dutch UI strings (single source; English code/comments)
├── tools/
│   └── migrate_rds.py        # one-time R .rds → SQLite import (§15)
├── crontab-scripts.sh        # GENERATED for the operator: copy-paste cron lines (§13)
└── tests/
```

(Legacy `test_*.py`, `explore_*.py`, capture JSON, `trace.zip` stay where they are; do not ship them in the app package.)

---

## 6. Data model (SQLite, multi-user, store-aware)

All user data is scoped by `user_id`. A **user = one PLUS account**. No data is global except the
optional shared product cache.

| Table | Columns (essential) | Notes |
|---|---|---|
| `users` | `id` PK, `plus_email_enc` (Fernet), `display_name`, `store_number`, `user_store_id`, `one_welcome_user_id`, `created_at`, `last_login_at`, `settings_json` | `plus_email_enc` encrypted at rest. `store_number` chosen on first login (§9.1). `settings_json` holds ML prefs, ntfy config, remember-me flag. |
| `credentials` | `user_id` FK, `password_enc` (Fernet), `remember` bool | Row exists only if the user opted into remember-me (§17). Otherwise nothing persisted. |
| `dishes` | `id` PK, `user_id` FK, `name`, `prep_notes` (markdown/text), `created_at`, `archived` bool | `prep_notes` is the recipe/preparation text shown in app + exported to iCal (§14). |
| `dish_ingredients` | `id` PK, `dish_id` FK, `sku`, `display_name`, `amount` (float), `amount_unit` (e.g. g, ml, stuks), `pack_size` (float), `pack_unit`, `optional` bool, `sort_order` | Strict single SKU per ingredient (§9.3). `amount`+`pack_size` drive aggregation/pack-optimization (§10). |
| `ingredient_skus` | `sku` PK (per user store), `name`, `subtitle`, `image_url`, `pack_size`, `pack_unit`, `last_price`, `last_seen_available`, `last_checked_at` | Per-user-store cache of resolved product facts so the dish editor and aggregation don't re-fetch constantly. |
| `fixed_products` | `id` PK, `user_id` FK, `sku`, `display_name`, `default_qty`, `sort_order` | The "vaste boodschappen" staples, drag-orderable. |
| `weekmenu` | `id` PK, `user_id` FK, `slot` (enum: `ma..zo` for diner, `lunch1..lunch5`), `dish_id` FK nullable, `week_start` (date) | 7 dinner + 5 lunch slots. Persist per week so history/export work. |
| `product_cache` | `sku` PK, `store_number`, `name`, `subtitle`, `image_url`, `price`, `is_available`, `fetched_at` | Optional shared-ish search cache keyed by store; speeds search. TTL-refreshed. |

Substitute/fallback SKUs are **not** stored on the ingredient (dishes are strict). Fallbacks are
computed at add-to-cart time by the resolver (§9.3 / §8). If you later want to remember accepted
substitutions, add a `substitutions(user_id, primary_sku, chosen_sku, count)` table — design for it
but do not build it in v1.

**Purchase history** is **not** maintained as the app's own log — it is always derived from PLUS
(§21). Two complementary PLUS sources exist (both resolved and implemented):
- **Previously-bought catalogue** (`get_purchase_history_api`) — every product ever bought, online
  **and in-store** (account QR), deduplicated. **No dates.** This is the *breadth* signal (what the
  user buys at all).
- **Order history** (`get_order_list_api` + `get_order_detail_api`) — dated **online** orders with
  full line items (SKU, qty, price, category, delivery date). This is the *cadence/recency* signal
  (when, how often) — online only; in-store dates are unavailable anywhere.

Cache both to avoid re-fetching (purchase catalogue is ~2 s/2 pages; full order history is many
calls). Suggested tables, refreshed on a TTL / on-open:
- `purchased_products_cache(user_id, sku, brand, name, subtitle, slug, image_url, price, is_available, categories_json, fetched_at)`
- `order_cache(user_id, order_id, order_number, delivery_date, total_price, status, channel, is_active, fetched_at)`
- `order_item_cache(user_id, order_id, sku, name, subtitle, slug, quantity, price, category, available)`

The ML layer (§11) fuses these two sources into the `PurchaseHistory` interface. The
no-local-purchase-log decision holds: the catalogue endpoint already unifies online + in-store, so
the app records nothing of its own.

### 6.1 Cache freshness & precomputed artifacts (enables fast open — see §13)

The app must **open fast by reading DB caches, not by calling PLUS.** Everything expensive at open
is precomputed and stored. Add:

| Table | Columns | Purpose |
|---|---|---|
| `sync_state` | `user_id` FK, `resource` (enum: `orders`, `purchase_catalogue`, `promotions`, `products`, `ml`), `last_synced_at`, `last_status`, `detail_json` | One row per (user, resource). The single source of truth for "how fresh is this cache" — drives both the staleness badge in the UI and the cron/scheduler decisions. |
| `promotions_cache` | `user_id` (or `store_number`) FK, `week_start`, `payload_json`, `fetched_at` | This week's full promotions list, prefetched so Lane ③ paints instantly. |
| `ml_artifacts` | `user_id` FK, `kind` (enum: `recommender`, `replenishment`, `promo_match`), `blob` (pickled/json model or precomputed scores), `trained_at`, `input_hash` | **Precomputed ML outputs.** Models are trained/scored by a background job, not at open. The UI loads the artifact and renders; it never trains on the request path. `input_hash` lets a job skip recompute when history hasn't changed. |

`product_cache` and `purchased_products_cache`/`order_*_cache` already cover product/history breadth;
`sync_state` ties them together so the app knows what's stale without probing PLUS.

**Rule: nothing on the open path calls PLUS except login + the live-cart fetch.** Promotions,
purchase/order history, product facts, and ML suggestions all read from the tables above. A
background refresh (in-app scheduler and/or cron, §13) keeps them warm. Stale-but-present always
beats blocking — render the cache immediately, then revalidate quietly and update in place.

---

## 7. PLUS integration layer (reuse + extend)

The existing `plus/` package already provides, per the README and ARCHITECTURE.md:

- `PlusClient.login(email, password)` — OAuth2 browser login (~3–5 s).
- `get_session_state()` — captures `CheckoutId`, `CheckoutVersion`, `OneWelcomeUserId`,
  `store_number` (e.g. 720), `user_store_id`, module/apiVersion hashes, current `LineItemId`s.
- `add_to_cart_api(sku, quantity)` / `remove_from_cart_api(sku, quantity)` — ~400 ms, atomic via
  `CheckoutVersion`.
- `get_cart()` / cart read via `DataActionGetCartById`.
- `get_promotions_api(next_week=False)` → `PromotionResult` (period + list of `Promotion`).
- `get_promotion_products_api(slug)` → `[PromotionProduct]` with `is_available` for the store.
- `version_cache` — disk cache of action apiVersion hashes; auto-invalidates on
  `hasApiVersionChanged`.

**You must extend the package with:**

1. **Product search** — `search_products_api(query, store_number) -> [Product]`. Endpoint:
   `DataActionGetProductListAndCategoryInfo` under
   `ECP_Composition_CW/ProductLists/PLP_Content/` (named in ARCHITECTURE.md "what remains"). Pass
   `StoreNumber` so each result carries `is_available` for that store. Return name, sku, subtitle,
   image, price, availability. Cache apiVersion the same way as the others (capture-once pattern).
   If the exact payload needs discovery, mirror the existing `explore_promotions.py` capture
   approach and document it.

2. **Store selection support** — a way to set/confirm a user's store on first login. The client
   already captures the account's preferred `store_number`; surface it and allow the user to
   confirm/override it (§9.1). Persist on the `users` row.

3. **Purchase & order history** — **already implemented; reuse, do not rewrite** (see §21 and
   ARCHITECTURE.md):
   - `get_purchase_history_api(all_pages=True, page_size=36) -> list[PurchasedProduct]` —
     every product ever bought (online + in-store, deduplicated, ~70 items / 2 pages). No dates.
   - `get_order_list_api(offset=0) -> list[OrderSummary]` — dated online orders (paginate; 100+
     exist). Each has `order_id`, `delivery_date`, `total_price`, `status`, `channel`, `is_active`.
   - `get_order_detail_api(order_id) -> OrderDetail` — full line items (`OrderLineItem`: sku, name,
     subtitle, slug, quantity, price, category, image_url, available).
   Wire these into `services/history.py` behind the `PurchaseHistory` protocol (§11) so the ML layer
   is endpoint-agnostic. Models for all of these already exist in `plus/models.py`
   (`PurchasedProduct`, `OrderSummary`, `OrderDetail`, `OrderLineItem`).

**Hard constraints carried from ARCHITECTURE.md (do not relearn the hard way):**
- All API calls go through `page.evaluate(fetch(...))` inside the logged-in browser context. Direct
  `httpx` returns 403. Keep one Playwright context per active user session.
- Every write sends the latest `CheckoutVersion`; always update it from responses.
- Each user has their own `store_number` — **never hardcode 720.**
- apiVersion hashes are cached to disk and auto-rediscovered on `hasApiVersionChanged`. The cache now
  covers Add/Remove/Get/Promotions/PromoDetail **and** OrderList/OrderDetail/PurchaseHistory.
- Order/purchase-history apiVersions are primed on first use by navigating to `/bestellingen`,
  `/order-details?OrderId=…`, `/eerder-gekochte-producten` and intercepting the fired call — handled
  by the existing client; just be aware the first call to each is slightly slower.
- **Order-history payload is fragile:** `viewName` must be `AccountFlow.OrdersOverview` /
  `AccountFlow.OrderDetail` and the full `screenData.variables` must match the browser exactly — a
  wrong payload silently returns all items as unavailable (`Quantity=0`) with no error. The existing
  client gets this right; do not "simplify" those payloads.

---

## 8. The live cart (the real PLUS cart, on screen)

There is **no local staging basket.** The on-screen cart is a live view of the PLUS cart.

**Lifecycle:**
1. On login + session-state capture, **fetch the current PLUS cart** (`get_cart`) and render it.
   (The user may already have items; show them.)
2. Adding/removing from any lane calls `add_to_cart_api` / `remove_from_cart_api`.
3. **Optimistic UI:** update the cart panel immediately on tap; show a subtle per-line sync
   indicator; reconcile with the API response (authoritative `CheckoutVersion`, totals,
   `LineItemId`s). On failure, revert the line and show a quiet inline error (not a modal).
4. Debounce rapid qty-stepper taps: coalesce into a single `QuantityToAdd`/`QuantityToRemove` call
   per line (use the atomic quantity delta — never loop single adds).
5. The cart shows: product image, name, unit/pack, qty stepper, line price, and a running **total**
   plus a **savings counter** ("−€X" from promotions) computed from cart contents vs original
   prices.

**Desktop:** pinned right-hand column, always visible.
**Mobile:** a **collapsed bottom bar** (item count · total · −€saved). Tapping it slides up the full
cart sheet. Adding an item gives a brief, restrained bump/scale on the bar — no fly-to-cart confetti
(see §16 motion rules).

The final "bestellen"/checkout is **not** automated — the cart links out to PLUS for the user to
confirm payment/slot themselves (§18 non-goals). Provide a clear "Afronden op plus.nl" button that
deep-links to the PLUS cart/checkout.

---

## 9. Screens & information architecture

Three screens: **Login**, **Cockpit** (primary), **Dishes**, **Settings**. Top-level nav is a slim
left rail on desktop / bottom nav on mobile (but the Cockpit is where ~90% of time is spent).
**UI language is Dutch** (strings in `i18n.py`); code and comments are English.

### 9.1 Login

- Clean, single-card login: PLUS email + password, "Onthoud mij" (remember-me) checkbox.
- On submit: run `PlusClient.login` (~3–5 s) with a **progress indicator** (animated, not a spinner
  that looks frozen — show "Inloggen bij PLUS…", "Winkelwagen ophalen…").
- **Remember-me:** if checked, store encrypted credentials (§17) so next visit auto-fills / auto-logs
  in. If unchecked, persist nothing.
- **First login ever for a user:** after auth, capture the account's preferred `store_number` and
  show a **store confirmation step**: "Je winkel: PLUS Utrecht #720 — klopt dat?" with the
  ability to choose another store. Persist on `users`. Subsequent logins skip this.
- Multi-user: each login establishes an isolated server-side session keyed to that PLUS account.
  Never mix users' data or carts (§17).
- After login: fetch current cart (§8) and route to the Cockpit.

### 9.2 Cockpit — the single-surface command center

One screen, four lanes (left/center) + live cart (right desktop / bottom mobile). Lanes are
vertically stacked sections on mobile, arrangeable columns/cards on desktop. Each lane is
independently usable; the cart reflects all of them live.

**Lane ① Deze week (meals).** The weekly planner — 7 dinner slots (Ma–Zo) + 5 lunch slots.
- Each slot is a card. Empty slot → "kies gerecht" (searchable dish dropdown with image + name).
  Filled slot → dish name, small image, quick actions: **swap**, **clear**, **view prep**.
- Choosing a dish does **not** silently dump items in the cart. Instead it stages the dish's
  resolved ingredients into a **"Toevoegen aan mandje"** review for this lane (respects the
  never-auto-add default). A prominent **"Voeg weekmenu toe aan mandje"** button adds all selected
  dishes' aggregated, pack-optimized ingredients in one go (§10), with the savings/aggregation
  summary shown first.
- If the ML recommender is enabled (§11), the planner can open **pre-filled** with suggestions
  (clearly marked as suggestions, one tap to accept/replace/clear each, plus "Plan mijn week" /
  "Shuffle"). Default (recommender off): slots start empty.
- Persist the week's selections in `weekmenu` (used by exports and history).

**Lane ② Vaste boodschappen (staples).**
- Shows the user's fixed products (drag-orderable, managed in Settings or inline).
- If replenishment ML is on (§11), items predicted **due** are highlighted with a short reason
  ("meestal wekelijks · 8 dagen geleden") and pre-selected; a **"Voeg alle verwachte toe"** button
  adds all due items in one tap. ML off: plain list with manual select + qty, like the R app.
- Never auto-adds to cart; selection → explicit add.

**Lane ③ Aanbiedingen voor jou (deals).**
- A browsable lane of this week's promotions **filtered/sorted to relevance** (matches the user's
  purchase history and current weekmenu; §11/§12). Each deal = product card with image, deal label
  (e.g. "1+1 GRATIS"), price, availability badge for the user's store, and a +stepper to add.
- Group deals (`is_single_product=False`) expand on tap to show qualifying products
  (`get_promotion_products_api(slug)`), each addable.
- **Inline swap prompts (level b):** when the user adds an ingredient/product elsewhere that has a
  promoted equivalent, surface a quiet inline suggestion ("Jan pizzadeeg is 1+1 gratis — wisselen?").
  One tap swaps the cart line. Non-nagging: at most one suggestion per item, dismissable.
- **No next-week promotions in-app** (per decision). (Next-week is used only by the ntfy job, §13.)

**Lane ④ Zoeken (search).**
- Instant, fuzzy product search via `search_products_api` at the user's store. Debounced
  (~250 ms), image-rich results, availability badge, +stepper. For the ad-hoc extras.
- Keep it fast and forgiving (typo-tolerant). This replaces the R "Extra artikelen" tab.

### 9.3 Dishes — the management redo

This is the part the owner explicitly wanted redone. The core failing of the old version: it was
unknown which ingredients are actually available at the user's store. Fix that by making
ingredient→SKU binding **strict, assisted, visual, and relinkable**, and availability a resolved
property surfaced where it matters.

**Dish list:** cards with name, ingredient count, a small set of ingredient thumbnails, and an
**at-a-glance availability status** computed from cached `ingredient_skus.last_seen_available`
("volledig beschikbaar" / "2 artikelen nu niet leverbaar"). Create / edit / archive / duplicate.

**Dish editor:**
- **Name** + **prep notes** (free text / light markdown). Prep notes are first-class — the owner
  reads them from the phone calendar via iCal (§14). Don't bury them.
- **Ingredients list** (drag-orderable). Each ingredient row:
  - **Assisted SKU mapping:** typing a name runs a live product search at the user's store; the user
    picks from image-rich results. The chosen product pins a **single strict SKU** (name, image,
    pack size, price cached into `ingredient_skus`). Dishes are strict — one SKU per ingredient.
  - **Amount + unit** (e.g. `300 g`, `2 stuks`) and the product's **pack size** (e.g. `650 g`),
    captured for aggregation/pack-optimization (§10).
  - **Optional** flag (some ingredients aren't always wanted) — carried from the R app's
    optional-ingredient concept.
  - **Relink:** an explicit "verander product" action to rebind the ingredient to a new SKU when a
    product changes/disappears. This must always be possible (SKUs do change).
- **Availability is a resolved property, surfaced at the right moment:** within the editor, show the
  product's last-known availability as informational. The *actionable* availability handling happens
  at **add-to-cart time** (next bullet), because "often-but-not-always available" is only a real
  problem when you actually try to buy.

**Add-to-cart resolution (the availability/fallback layer — NOT stored on the dish):**
- When dishes are added to the cart (from Lane ①), for each ingredient SKU check current
  availability at the store. If unavailable, present a **substitute suggestion** inline in the
  add-review: ranked candidates from product search (same category/keywords), and/or a promoted
  equivalent if one exists. The user picks or skips. The dish definition stays strict; only the cart
  line uses the substitute.
- This keeps dish *composition* clean and deterministic while making *shopping* self-healing.

### 9.4 Settings

A single, well-organized settings screen with clearly explained options (the owner wants the ML
preferences explained on the user's side, not opaque knobs):

- **Account & winkel:** display name, store (change with the same store picker as first login),
  remember-me toggle, log out, delete my data.
- **Slimme suggesties (ML)** — all OFF by default; each with a one-line plain-Dutch explanation:
  - Master toggle: "Slimme suggesties gebruiken" (uses your purchase history; nothing leaves your
    server; no AI in the cloud).
  - **Weekmenu-voorkeuren** (recommender weighting, see §11): sliders/toggles for
    *afwisseling* (don't repeat recent meals), *vaste dagen* (day-of-week habits),
    *voordeel* (prefer dishes whose ingredients are on sale), *voorraad* (use up staples due soon),
    *variatie* (spread across categories). Each with a short explanation of what it does.
  - **Voorraadvoorspelling** (replenishment highlighting on the staples lane) on/off.
  - **Autopilot** (opt-in): "Vul mijn mandje automatisch voor een routineweek" — even when ML is on,
    this is the ONLY setting that lets ML pre-fill the cart; default OFF. Explain clearly that it
    still requires the user to review and press the final order on PLUS.
- **Meldingen (ntfy):** per-user ntfy **instance URL**, **topic**, optional **username/password**;
  test-push button; weekly-alert toggle (§13).
- **Exports:** defaults for iCal (which slots, include prep notes) and the plain-text list (§14).

**Default posture (must hold):** ML off; when on, suggest-only; cart is never modified without an
explicit user tap unless Autopilot is explicitly enabled.

---

## 10. Pack-optimization / cross-dish aggregation engine

A genuine feature, not a detail. **Motivating example (use it as a test case):** dish A needs 300 g
chicken, dish B needs 300 g chicken. The store sells a 650 g pack cheaper per kg than two 300 g
packs. The app should buy **one 650 g pack** (split at home) instead of two 300 g packs, and **say
so prominently.**

`services/aggregate.py`:
1. **Collect** all ingredients across the selected weekmenu (Lane ①), keyed by a *consolidation key*
   — same SKU obviously consolidates; also consolidate ingredients the user has marked as the same
   underlying product even if entered per-dish. Sum required `amount` (respecting units; convert
   within a unit family g↔kg, ml↔l; never across families).
2. For each consolidated need, **choose the optimal pack combination** for the store: query the
   product's available pack sizes (the pinned SKU's pack, plus sibling pack-size variants found via
   product search where applicable), and pick the combination that covers the required amount at
   lowest total price (a tiny bounded knapsack — quantities are small; brute force is fine).
3. Produce an **aggregation summary** shown *before* items hit the cart:
   - "Kip: 2 gerechten × 300 g = 600 g → **1× 650 g (€X) i.p.v. 2× 300 g (€Y)** — bespaart €Z, thuis
     verdelen."
   - List each optimization line, total estimated savings, and any leftover ("50 g over").
4. On confirm, add the optimized packs to the live cart.

Constraints: optimization is **suggestive and transparent** — the user can expand any line and
override to "gewoon per gerecht" if they don't want to split at home. Optional ingredients are
included only if selected. Never silently change quantities without the summary.

Edge cases to handle: unit mismatch (fall back to per-dish if not convertible), unavailable optimal
pack (use next-best available), single-dish ingredients (no aggregation, still pack-rounded).

---

## 11. Intelligence layer (local ML)

All models are **local, explainable, offline. No LLM.** They are **off by default**, configured in
Settings (§9.4), and **never write to the cart** unless Autopilot is explicitly enabled.

**Single data dependency:** all models read through one interface, which **fuses the two PLUS
sources** (§6/§21):

```python
# ml/interface.py
class PurchaseHistory(Protocol):
    def items(self, user_id: int) -> list[PurchaseRecord]: ...
    # PurchaseRecord:
    #   sku, name, category: str | None
    #   ever_bought: bool          # from purchase-history catalogue (online + IN-STORE)
    #   last_bought: date | None   # from dated ORDER history — None if only ever bought in-store
    #   order_count: int           # number of dated online orders containing it
    #   frequency: float | None    # buys/week, derived from dated orders; None if undatable
    #   dates_complete: bool       # False when in-store purchases (no dates) likely dominate
```

`services/history.py` builds these records by **merging**:
- `get_purchase_history_api()` → the full breadth (every SKU ever bought, incl. in-store). Sets
  `ever_bought` and gives names/categories/prices/availability.
- `get_order_list_api()` + `get_order_detail_api()` → dated cadence: `last_bought`, `order_count`,
  `frequency`. **Online orders only** — in-store (QR) purchases have no dates anywhere in the API.

**The dating gap is a first-class concern, not an edge case.** A product the user buys only in the
physical store appears in the catalogue (`ever_bought=True`) but has `last_bought=None` /
`frequency=None`. Models must treat "undatable" distinctly from "never bought" — never assume
absence of an order means absence of purchase. Set `dates_complete=False` for such items and let
each model decide (below). Cache order detail aggressively (§6); fetching all 100+ orders is the
expensive path — do it once, then incrementally pull only new orders on refresh (orders are
immutable once delivered).

**Cold-start / sparse data:** degrade gracefully — recommender falls back to recency over the local
`weekmenu` table; replenishment shows all staples with none pre-selected; promo-match falls back to
matching against weekmenu ingredients only. Never error; get smarter as history accumulates.

**Precomputed, never on the request path.** Training/scoring happens in the `recompute_ml` background
job (§13), which writes results to `ml_artifacts` (§6.1). The UI **loads the artifact and renders** —
it must never train, fetch history, or call PLUS to produce a suggestion at open time. All three
models below read their inputs from the DB caches (history, promotions, products), not from live API
calls. If an artifact is missing/stale, fall back to cold-start behavior and trigger a background
recompute — don't block.

### 11.1 Week-menu recommender (`ml/recommender.py`)
Suggests dishes for the 12 slots. Signals, **weighted by user settings** (§9.4):
- **Afwisseling/recency:** down-weight dishes cooked recently (from `weekmenu` history).
- **Vaste dagen:** day-of-week affinity (e.g. tends to eat X on Wednesdays) — learn per-slot
  frequencies.
- **Voordeel:** boost dishes whose ingredient SKUs are in this week's promotions.
- **Voorraad:** boost dishes using staples predicted due (from replenishment model).
- **Variatie:** penalize repeating the same category within the week.
Model: a transparent weighted score per (dish, slot) — e.g. logistic/`GradientBoosting` on
engineered features, or a clear hand-tuned linear blend if data is thin. Must expose **why** a dish
was suggested (short reason chips). "Plan mijn week" fills all slots greedily respecting variety;
"Shuffle" reshuffles with the same weights.

### 11.2 Replenishment (`ml/replenish.py`)
Per staple SKU, estimate purchase cadence from **dated order history** → a **due score**. Drives the
highlighting/pre-selection in Lane ②. Simple, robust: expected interval = mean inter-purchase gap
from dated orders; due if `days_since_last >= interval * threshold`. Expose the reason string
("meestal wekelijks · 8 dagen geleden"). **Handle the dating gap:** for a staple with
`dates_complete=False` (bought in-store, no usable dates), don't claim a confident due-date — fall
back to a softer "vaak gekocht" highlight without a countdown, or skip pre-selection. Never invent a
cadence from undated data.

### 11.3 Promotion matcher (`ml/promo_match.py`)
Score each of this week's offers by relevance = f(breadth `ever_bought`, dated `frequency`/recency
where available, presence in current weekmenu ingredients, category affinity). Crucially, **use
`ever_bought` (catalogue breadth) so in-store-only products still match** — a deal on something the
user regularly buys in the physical store is highly relevant even with no online order dates.
Produces the ordering for Lane ③ and the candidate set for the ntfy job (§13). Pure ranking; no cart
effects.

---

## 12. Promotions handling

- Use `get_promotions_api()` (current week only in-app) and `get_promotion_products_api(slug)` for
  group deals. ~400 ms each; cache within a session.
- **Lane ③** renders them relevance-ranked (§11.3 when ML on; otherwise category order as returned).
- **Savings counter** in the cart (§8): for each cart line that matches an active promotion, compute
  the discount vs original price and sum into "−€X". Keep it factual and quiet (§16) — show the
  number, no celebratory language.
- **Inline swap (level b):** maintain a quick lookup from a product/ingredient to any promoted
  equivalent (same category/brand/keyword) so the add flow can offer a one-tap swap. At most one
  prompt per item; dismissable; never blocks the add.
- Free-delivery promos (`is_free_delivery`) and single-product vs group deals are already
  distinguished by the client models — render appropriately (free-delivery as an informational
  banner, not an addable card).

---

## 13. Background jobs, preloading & scheduled refresh

**The problem this solves:** cold app-open is slow because it would otherwise fetch promotions,
purchase/order history, and product facts and train ML on the request path. **It must not.** All of
that is precomputed by background jobs into the DB caches (§6.1), so opening the app is: log in →
fetch the live cart → paint everything else from cache. The "under 2 minutes" target depends on this.

### 13.1 Jobs as both scheduler tasks AND cron entrypoints

Every background job is a plain async function in `jobs/registry.py`, runnable two ways:
1. **In-app** via APScheduler (`jobs/preload.py` registers them on startup) — so the app self-maintains
   even if the operator sets up no cron.
2. **Standalone** via a CLI: `uv run python -m pyplus.jobs <name> [--user all|<id>]` — so the
   operator can drive them from the system `crontab` with full freedom (the owner explicitly wants
   this). The CLI shares the exact same job bodies; it boots a minimal app context (DB + config + a
   per-user `PlusClient`), runs the named job, writes `sync_state`, and exits.

Make the two paths **idempotent and mutually safe** (a lightweight per-(user,resource) lock or an
"in progress" flag in `sync_state`) so a cron run and an in-app run never collide. Default posture:
ship sensible in-app schedules; let cron override/augment. Document that if the operator prefers
cron, they can disable the in-app scheduler via env (`PYPLUS_DISABLE_SCHEDULER=1`).

### 13.2 Named jobs (what gets precomputed, and when)

| Job (`<name>`) | What it does | Suggested cadence | Needs creds? |
|---|---|---|---|
| `refresh_orders` | Incrementally pull new online orders → `order_cache`/`order_item_cache` (only orders newer than latest cached `delivery_date`; orders are immutable). | Daily, off-peak | yes |
| `refresh_purchase_catalogue` | Refetch the previously-bought catalogue → `purchased_products_cache`. | Daily | yes |
| `refresh_promotions` | Fetch this week's promotions → `promotions_cache`; on the publish day also next-week (for ntfy). | Daily; + on promo publish day | yes |
| `refresh_products` | Re-validate prices/availability for SKUs the user actually uses (dish ingredients, fixed products, recent cart) → `ingredient_skus`/`product_cache`. | Daily | yes |
| `recompute_ml` | Train/score the three models from the warmed caches → `ml_artifacts` (skip if `input_hash` unchanged). | After the refresh jobs (e.g. nightly) | no (reads DB) |
| `weekly_ntfy` | The promotions alert (§13.4). | Weekly, promo publish day | yes |
| `full_preload` | Convenience: runs all of the above in dependency order for one or all users. | Operator's call | yes |

**Dependency order** (important for `full_preload` and for cron sequencing):
`refresh_orders` + `refresh_purchase_catalogue` + `refresh_products` + `refresh_promotions` →
**then** `recompute_ml` → then `weekly_ntfy`. ML reads the caches the refresh jobs produce, so it
must run after them.

### 13.3 The `crontab-scripts.sh` deliverable (Sonnet must generate this for the operator)

Produce a committed, **personal-info-free** `crontab-scripts.sh` at the repo root that:
- Documents, in comments, what each job does and the recommended schedule.
- Contains ready-to-paste `crontab -e` lines invoking the CLI with absolute-path placeholders the
  operator fills in (`/path/to/app`, the `uv` binary, the env file). Use placeholders only — **no
  real paths, emails, or domains** (§17).
- Example shape (illustrative — Sonnet finalizes job names/flags to match the implementation):
  ```sh
  # PyPLUS scheduled refresh — fill in <APP_DIR> and ensure PYPLUS_SECRET_KEY is set.
  # Nightly cache warm + ML recompute (02:30), promotions + ntfy on publish morning (Thu 07:00).
  30 2 * * *  cd <APP_DIR> && uv run python -m pyplus.jobs full_preload --user all   >> <APP_DIR>/logs/preload.log 2>&1
  0  7 * * 4  cd <APP_DIR> && uv run python -m pyplus.jobs weekly_ntfy  --user all   >> <APP_DIR>/logs/ntfy.log    2>&1
  ```
- A header comment explaining the prerequisite: jobs that hit PLUS need the user's stored (remember-me)
  credentials; users without them are skipped (see §13.4).
- The README must point to this file and explain the in-app-scheduler-vs-cron choice.

### 13.4 ntfy weekly alert (`jobs/weekly_ntfy.py`)

- Runs **weekly** when next-week deals publish (fixed weekday/time, `Europe/Amsterdam`, env-configurable).
- For each user with the ntfy alert enabled: read next-week promotions (from `promotions_cache`, or
  fetch if absent), run the promo matcher (§11.3) against that user's history, and on strong matches
  **push to that user's ntfy** instance (per-user URL + topic + optional username/password from
  Settings, §9.4).
- Message: concise Dutch, e.g. "3 producten die je vaak koopt zijn volgende week in de aanbieding: …"
  with a **deep link back into the app** (opens the deals lane / a pre-staged selection). No spam:
  push only above a match threshold; at most one push per user per week.
- Respect the quiet tone (§16): inform, don't cheer.

### 13.5 Jobs need credentials — the honest constraint

Any job that calls PLUS (everything except `recompute_ml`) needs a logged-in session **without the
user present**, so it depends on that user's encrypted remember-me credentials (§17). Users who
haven't opted into remember-me simply **don't get background preloading or ntfy** — their app-open
will be slower (it warms caches on first open instead) and they get no push. Make this explicit in
Settings ("Sla mijn inloggegevens op — nodig voor sneller laden en meldingen") and in the README.
Never fabricate or share sessions across users.

### 13.6 First-open / empty-cache behavior

If a user opens the app with cold caches (new user, or no remember-me so cron never ran for them):
paint the shell + live cart immediately, show skeletons in the cache-backed lanes, and warm the
caches **in the background** (same job bodies, triggered on-demand), filling lanes in as each
completes. Never block the whole screen on a full preload. The second open (or the next cron run) is
then fast.

---

## 14. Exports (`services/exports.py`)

Two exports, both first-class (the owner uses them).

**iCal (must-have).** Export the current `weekmenu` as a calendar the user subscribes to / imports on
their phone.
- One event per filled slot, on the correct date, titled with the dish name (dinner vs lunch
  distinguished).
- **Event description includes the dish's prep notes** — this is the key use case: standing at the
  cupboard, the user opens the calendar to see what to get out and how to prepare it. Optionally list
  ingredients too (Settings toggle).
- Use the `icalendar` package. Provide both a downloadable `.ics` and, ideally, a stable per-user
  subscription URL (`webcal`/HTTP) so the phone stays in sync — if a subscription URL adds auth
  complexity, ship the `.ics` download for v1 and note the subscription URL as a fast follow.

**Plain-text shopping list (must-have).** A printable text list for when the user can't wait a day
and shops in person.
- Derived from the current selection/cart: product names + quantities, grouped sensibly (e.g. by
  PLUS category or by lane), plain UTF-8, copy-to-clipboard + download.
- Keep it terminal/printer-friendly (the R app had a plain-text popup; match that spirit).

Both exports are also reachable from the Cockpit (not buried in Settings) — Settings only holds their
defaults.

---

## 15. Migration from R `.rds` (`tools/migrate_rds.py`)

The owner has substantial existing data and wants **all of it kept**. Build a one-time importer.

- Source `.rds` files (per the R app): `product_list.rds`, `dishes-{email}.rds`,
  `dish_ingredients-{email}.rds`, `weekmenu-{email}.rds`, `fixed_products-{email}.rds`,
  `basket-{email}.rds`. Locate them under the R app's data dir (see `R/zzz.R` for resolution logic).
- Conversion path (from plan.md): use R itself to dump to CSV
  (`Rscript -e "write.csv(readRDS('x.rds'), '/tmp/x.csv')"`), then import CSV → SQLite. Script this so
  it's repeatable; don't require the owner to hand-run each one.
- Map fields: dishes → `dishes` (+ `prep_notes` from the R prep field), ingredients →
  `dish_ingredients` (carry `optional` flag, `qty`/label → `amount`/units as best as available;
  where pack size is unknown, leave null and let the dish editor backfill on first edit),
  fixed products → `fixed_products` (preserve `sort_order`), weekmenu → `weekmenu`.
- **Ingredient SKUs:** the R app linked products by `product_url`, not SKU. Resolve URLs/names to
  SKUs at the user's store via product search during import; where ambiguous, import the ingredient
  unmapped and **flag it for the user to relink** in the dish editor (don't guess silently).
- Idempotent: safe to re-run; don't duplicate rows.
- Provide a short import report (counts imported, ingredients needing relink).

---

## 16. Visual design system (`ui/theme.py`)

**Direction:** an **own, premium identity** — NOT a clone of the PLUS website. Modern, clean,
"fintech-grade" polish. PLUS green is the **primary accent**, not the whole UI.

- **Brand palette (from the R app, reuse exactly as accents):**
  - PLUS red `rgb(227, 19, 29)` — destructive/alerts only, sparingly.
  - PLUS green-light `rgb(128, 189, 29)` — primary accent / positive.
  - PLUS green-dark `rgb(34, 118, 71)` — secondary/deep accent.
  - PLUS purple `rgb(85, 77, 167)` — occasional highlight.
  - Neutrals: a refined gray scale for surfaces/text; generous whitespace; soft shadows; rounded
    corners (consistent radius scale); a clear type scale (a clean sans; the R app used Google
    Fonts via bslib — choose one tasteful modern face, e.g. Inter).
- **No dark mode** for v1 (don't build it; keep tokens themeable so it's a later flip).
- **Components:** product card, qty stepper, dish card, cart line, lane container, suggestion chip,
  promo ribbon, availability badge, aggregation-summary panel. Build them once in `ui/components/`
  and reuse — visual consistency is non-negotiable.
- **Motion — the taste rule (read carefully):** liveliness is welcome; **childish/American
  cheerleading is forbidden.** No confetti. No "Great job on the savings!! ♥♥♥". No emoji-spam, no
  bouncing mascots. Allowed: smooth transitions, gentle scale/opacity on add, skeleton shimmer on
  load, a quiet number tick on totals, subtle hover states. European restraint: polished, calm,
  fast. When in doubt, make it quieter.
- **Feel:** optimistic and instant. Nothing blocks on the network if it can update optimistically.
  Skeletons over spinners. Inline, quiet errors over modals.
- **Responsive:** desktop = stage + pinned right cart; mobile = stacked lanes + bottom-bar cart
  (§8). Touch targets generous; the whole shop must be comfortable one-handed on a phone.

---

## 17. Security, secrets & GitHub hygiene

The repo is **public on GitHub.** Absolute rules:

- **The owner's email and domain must NEVER appear in the repo** — not in code, configs, comments,
  fixtures, commit messages, or test data. Use placeholders (`you@example.com`, `example.com`).
- **Nothing sensitive is committed:** gitignore the data dir, the SQLite DB, `.env`, any
  `*credentials*`, `api_versions.json`, Playwright `trace.zip`, capture JSON, the `logs/` dir, and
  any persisted `ml_artifacts`/cache exports. Ship only `.env.example` and `*.example` configs.
  `crontab-scripts.sh` **is** committed but must contain only placeholders — no real paths/emails/domains.
- **Credentials at rest:** stored PLUS passwords/emails are encrypted with **Fernet**; the key comes
  from an env var (`PYPLUS_SECRET_KEY`) the *server operator* sets — never committed, never
  defaulted to a literal. If the key is absent, remember-me is disabled (fail safe), not bypassed.
- **Multi-user isolation:** every DB query is scoped by `user_id`; each session has its own
  `PlusClient`/Playwright context and PLUS cart. A user can never see or affect another user's data
  or cart. Validate the session's user on every action.
- **Light touch otherwise:** this is a personal/family tool behind a reverse proxy. Don't over-engineer
  auth (no OAuth provider, no RBAC). Reasonable session handling + the encryption above is enough.
- Add a brief `SECURITY` note in the README about the secret key and the gitignore expectations.

---

## 18. Non-goals (do not build)

- **No payment/checkout automation** — the user presses the final "bestellen" on plus.nl themselves.
- No nutrition/calorie/macro tracking.
- No in-app barcode scanning.
- No social/sharing features.
- No web-recipe import.
- No next-week promotions in the UI (next-week is only for the ntfy job).
- No local staging basket (the live PLUS cart is the basket).
- No dark mode (v1).
- No LLM/cloud-AI anywhere.

If tempted to add anything here "because it's easy," don't. It dilutes the single goal.

---

## 19. Build order / milestones

Build in this order; each milestone should be runnable/demoable.

0. **No gate** — all PLUS endpoints (cart, promotions, product search, purchase + order history) are
   resolved. Build straight through.
1. **Foundations:** uv project, config, SQLite + SQLAlchemy + Alembic, design tokens/theme, app
   shell + nav, Dutch i18n scaffold.
2. **Auth & session:** login page, `PlusClient` per-user session, store confirmation on first login,
   encrypted remember-me. Fetch & render current cart.
3. **Live cart:** optimistic add/remove, debounced steppers, reconcile, totals + savings, desktop
   pinned column + mobile bottom bar.
4. **Search lane (④):** product search client method + lane UI + add-to-cart.
5. **Dishes redo:** data model, dish list + editor, assisted SKU mapping, relink, prep notes,
   amount/pack capture, availability surfacing.
6. **Migration:** `tools/migrate_rds.py` — import the owner's real data; produce the relink report.
7. **Meals lane (①) + aggregation engine (§10):** planner, staged add, cross-dish pack optimization
   with prominent summary. Verify the chicken example.
8. **Staples lane (②)** (manual first) and **Promotions lane (③)** + inline swaps + savings counter.
9. **Exports:** iCal (with prep notes) + plain-text shopping list.
10. **Caching & background infrastructure (§6.1/§13):** `sync_state` + cache tables, the job
    registry, the `python -m pyplus.jobs` CLI, the in-app APScheduler wiring, and the generated
    `crontab-scripts.sh`. Make the open path cache-only (login + live cart aside). Verify a warmed
    open paints with no PLUS calls beyond login/cart.
11. **Intelligence layer:** build `services/history.py` — fuse `get_purchase_history_api` (breadth,
    incl. in-store) with `get_order_list_api`/`get_order_detail_api` (dated cadence) behind the
    `PurchaseHistory` interface, reading from the caches built in step 10; then recommender,
    replenishment, promo-matcher, each precomputed into `ml_artifacts` by `recompute_ml` (never on
    the request path); Settings ML controls with explanations; all off by default. Respect the
    dating-gap rules (§11).
12. **ntfy weekly job** (the `weekly_ntfy` job body + Settings + deep link).
13. **Polish pass:** motion, skeletons, empty states, error states, mobile ergonomics, performance
    (the <2-minute routine-week target; verify the fast-open criterion). Verify success criteria (§2).

---

## 20. Testing & acceptance

- **Unit:** aggregation/pack-optimization (incl. the chicken case and unit-conversion edges); ML
  models against fixture histories (incl. cold-start); ingredient resolution/relink; exports
  (iCal structure, plain-text formatting).
- **Integration (against the real PLUS client, gated/manual):** login, cart add/remove/reconcile,
  search, promotions — reuse/extend existing `test_*.py`. Keep these out of the shipped package and
  free of personal data.
- **Jobs/preload:** each named job is idempotent and updates `sync_state`; the CLI entrypoint runs a
  single job and exits cleanly; cron and in-app scheduler don't collide; a warmed open performs no
  PLUS calls beyond login + cart (assert this).
- **Acceptance:** walk the §2 success criteria explicitly. Time a routine-week run; confirm fast-open.
- Run `ruff` (lint+format) and `pytest` clean before declaring done.

---

## 21. RESOLVED — Purchase & order history endpoints

> **Status: SOLVED and implemented** in `plus/client.py` / `plus/models.py`. Full detail is in
> `ARCHITECTURE.md` ("Order history" and "Previously bought products" sections). Reuse the existing
> methods; do **not** rewrite them. Summary below is what the app layer needs.

There are **three** history methods, providing two complementary signals:

**A. Previously-bought catalogue — `get_purchase_history_api()`** *(the breadth signal)*
- Endpoint: `ECP_Customer_CW/Account/RecentlyBoughtProducts/DataActionGetProducts`
  (`viewName: AccountFlow.RecentlyBoughtProducts`).
- Params: `CurrentPageNumber`, `UserStoreId`, `OneWelcomeUserId`. A `Period` field is required by the
  schema but **ignored** by the server — always returns the full all-time history. Paginated 36/page
  (~70 products / 2 pages, ~2 s).
- Returns every product **ever bought, online AND in-store** (account QR), deduplicated →
  `list[PurchasedProduct]` (sku, brand, name, subtitle, slug, image_url, price, is_available,
  categories). **No purchase dates at this level.**

**B. Order list — `get_order_list_api(offset=0)`** *(dated online orders)*
- Endpoint: `ECP_Customer_CW/Account/OrdersContent/DataActionGetCustomerDetails`
  (misleadingly named — returns orders, not profile; `viewName: AccountFlow.OrdersOverview`).
- Params: `OneWelcomeUserId`, `QueryOffset` (paginate; 100+ orders exist).
- Returns `list[OrderSummary]` (order_id UUID, order_number, delivery_date, delivery window,
  total_price, status "Bezorgd"/"Opgehaald"/"In behandeling", channel "Web"/"App", is_active).

**C. Order detail — `get_order_detail_api(order_id)`** *(line items for one order)*
- Endpoint: `ECP_Customer_CW/CustomerDetails/OrderDetailsContent/DataActionGetOrderDetails`
  (`viewName: AccountFlow.OrderDetail`).
- Params: `OrderId` (UUID), `OneWelcomeUserId`, `ExternalChannelId`.
- Returns `OrderDetail` with `items: list[OrderLineItem]` (sku, name, subtitle, slug, quantity,
  price, category, image_url, available). Delivered items have `available=True, quantity>0`;
  items that couldn't be delivered come back `available=False, quantity=0`.

**Critical fragility (already handled by the client — don't "simplify"):** the order endpoints live
on separate OutSystems apps that re-initialise on navigation. `viewName` must be exactly
`AccountFlow.OrdersOverview` / `AccountFlow.OrderDetail` (NOT `MainFlow.*`) and the full
`screenData.variables` must match the browser. A wrong payload **silently** returns everything as
unavailable (`Quantity=0`) with no error.

**How the app uses them (see §11):**
- **Breadth** (what the user buys at all, incl. in-store) → `get_purchase_history_api` → sets
  `ever_bought`. This is the only source that captures in-store purchases.
- **Cadence/recency** (when, how often) → order list + detail → `last_bought`, `order_count`,
  `frequency`. **Online only.** A product bought solely in-store has `ever_bought=True` but no dates;
  `services/history.py` marks it `dates_complete=False` and the models treat it accordingly (§11).
- **No-local-purchase-log decision CONFIRMED:** the catalogue endpoint unifies online + in-store, so
  the app records nothing of its own — it derives everything from these endpoints and caches (§6).
  The only inherent limitation is that in-store purchases carry no dates anywhere in PLUS's API; this
  is an API limitation, not a reason to add a local log.

**Performance note:** building full cadence means fetching order detail for many orders (100+).
Orders are immutable once delivered — fetch all once into `order_cache`/`order_item_cache` (§6), then
on refresh pull only orders newer than the latest cached `delivery_date`. Don't refetch the whole
history every open.

---

*End of build instruction. This document is authoritative; `plan.md` is superseded where they
differ. The PLUS API mechanics in `ARCHITECTURE.md` remain authoritative for integration details.*
