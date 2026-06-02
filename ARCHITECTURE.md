# PyPLUS → Python: Technical Architecture

## What This Is

A personal Dutch grocery planning app. Users plan weekly meals, manage a recipe/dish database, and send a shopping basket to their PLUS.nl online supermarket cart. The current version is R/Shiny. This document describes the Python rewrite in progress.

---

## PLUS.nl Integration (the hard part — now solved)

PLUS.nl runs on **OutSystems**, a low-code platform. There is no public API. Their web frontend is a React SPA calling internal `screenservices` endpoints.

### Login

OAuth2 browser flow via `aanmelden.plus.nl` (`client_id=web_ecop_eprod`). Unavoidable — requires a real browser. Implemented with **Playwright** (Python, headless Chromium). Takes ~20s once per session.

After login, all subsequent operations are direct HTTP calls via `page.evaluate(fetch(...))`. No browser navigation or DOM interaction.

### Direct API calls (post-login)

All operations are `POST` requests to `https://www.plus.nl/screenservices/`. Cart actions are under `ECP_Cart_CW`; promotions are under `ECP_Composition_CW`:

**Cart** — `ECP_Cart_CW/`:

| Operation | Endpoint | Key parameters |
|---|---|---|
| Add item | `ActionCheckoutItem_Add` | `SKU`, `QuantityToAdd`, `CheckoutId`, `CheckoutVersion` |
| Remove item | `ActionCheckoutItem_Remove` | `SKU`, `LineItemId`, `QuantityToRemove`, `CheckoutId`, `CheckoutVersion` |
| Read cart | `DataActionGetCartById` | `CheckoutId` |
**Promotions** — `ECP_Composition_CW/Promotions/Promotion_LP_Content_TF_Optimization/` and `ECP_Promotion_CW/PromotionDetailsFlow/PromotionOffer_DP_Content/`:

| Operation | Endpoint | Key parameters |
|---|---|---|
| All deals, all categories | `DataActionGetPromotionList_Optimization` | `StoreNumber`, `UserStoreId`, `OneWelcomeUserId`, `IsNextWeekPromotions` |
| Products behind a group deal | `DataActionPromotionOfferDetail_Get` | `PromotionOfferId` (slug), `StoreNumber`, `CheckoutId` |

`DataActionGetPromotionList_Optimization` uses `screenData.variables` (OutSystems screen data action) rather than `inputParameters`. One call returns all 17 category sections (~148 offers) for the full week. `IsNextWeekPromotions: true` switches to next week. The `EmptyListItem` type schema for `LocalPromotionList` must be sent verbatim (hardcoded constant `_PROMO_EMPTY_ITEM` in `client.py`).

`DataActionPromotionOfferDetail_Get` is called on-demand with a promotion `slug` (e.g. `"4431-96"`) and returns the individual products qualifying for that group deal — name, SKU, subtitle, image, original price, and per-product deal label. Note `StoreChannelD` (trailing D) in this payload, distinct from `StoreChannel` in the promotions list payload.

**Speed:** ~400ms per call (vs 20–30s in the R/Chromote version, and no double-add bugs).

**Order history** — `ECP_Customer_CW/Account/OrdersContent/` and `ECP_Customer_CW/CustomerDetails/OrderDetailsContent/`:

| Operation | Endpoint | Key parameters |
|---|---|---|
| All past orders (list) | `DataActionGetCustomerDetails` | `OneWelcomeUserId`, `QueryOffset` |
| Full line items per order | `DataActionGetOrderDetails` | `OrderId` (UUID), `OneWelcomeUserId`, `ExternalChannelId` |

`DataActionGetCustomerDetails` (misleadingly named — returns order history, not customer profile) returns `Orders_Struct_Active` (upcoming) and `Orders_Struct_Previous` (past) lists. Each order has `Order_Id` (UUID), `Order_Number`, `Order_DeliveryDate`, `Order_TotalPrice`, `DeliveryType_ServiceStatusLabel` ("Bezorgd"/"Opgehaald"), and `BusinessInterfaceId` ("Web"/"App"). Pagination via `QueryOffset`; the user has 100+ orders total.

`DataActionGetOrderDetails` returns the full receipt for one order: `AvailableItemList` (delivered, with `Quantity` > 0) and `UnavailableItemList` (couldn't be delivered, `Quantity` = 0). Each item has `SKU`, `Quantity`, `Name`, `Subtitle`, `Slug`, `Category`, `Price`.

These endpoints live on `/bestellingen` and `/order-details?OrderId=` pages — separate OutSystems apps that re-initialize on navigation. Critical: `viewName` must be `AccountFlow.OrdersOverview` / `AccountFlow.OrderDetail` (not `MainFlow.*`), and the full `screenData.variables` must match the browser exactly. Wrong payload silently returns all items as unavailable with `Quantity=0` — no error.

**Previously bought products (online + in-store)** — `ECP_Customer_CW/Account/RecentlyBoughtProducts/`:

| Operation | Endpoint | Key parameters |
|---|---|---|
| All ever-bought products | `DataActionGetProducts` | `CurrentPageNumber`, `UserStoreId`, `OneWelcomeUserId` |

Returns a deduplicated catalogue of all products ever purchased — both online orders and in-store purchases made with the account QR code. Paginated at 36 per page (~70 products across 2 pages). The `Period` field is required by the schema but ignored by the server; any date range returns the full all-time history. No purchase dates available at this level. `viewName` must be `AccountFlow.RecentlyBoughtProducts`.

### Authentication for API calls

Each screenservices call requires three things beyond the payload:
- **Session cookies** from the browser login (passed automatically via `page.evaluate(fetch(...), credentials: 'include')`)
- **`x-csrftoken` header** — the `crf=` field parsed from the `nr2Users` cookie
- **`outsystems-locale: nl-NL` header**

### The versioning problem (OutSystems-specific)

Every request body must include `versionInfo.moduleVersion` and `versionInfo.apiVersion`. These are **action-specific hashes baked into PLUS.nl's compiled JavaScript** — different for Add vs Remove vs GetCart. If stale, the server returns `hasApiVersionChanged: true` and an empty response.

**Solution:** Discover them once via a browser-intercepted request, then **cache to disk** (`~/.config/pyplus/api_versions.json`). Valid until PLUS.nl deploys a new version. On `hasApiVersionChanged: true`, cache is automatically invalidated and the next session re-discovers them.

### How versions are discovered (first session only)

1. Navigate to a product search page, click the add-to-cart button once → browser JS fires `ActionCheckoutItem_Add` with the correct `apiVersion` → intercepted by Playwright's `page.on("request")` → saved to cache
2. Navigate to cart, click quantity badge to open the `±` slider, click the remove button → browser JS fires `ActionCheckoutItem_Remove` → intercepted → saved to cache

This two-click setup happens exactly **once ever** (until PLUS.nl redeploys). All subsequent sessions load from cache.

### LineItemId

Each cart item has a server-assigned `LineItemId` (UUID) required for removal. Sources:
- Populated automatically from any cart API response (`ActionCheckoutItem_Add`, `ActionCheckoutItem_Remove` both return the full cart including all `LineItemId` values)
- Also populated from `DataActionGetCartById` responses which fire automatically when the cart page loads during session initialisation

### Store identifiers

PLUS uses two distinct store identifiers, both captured passively during login:

| Field | Value | Source | Used in |
|---|---|---|---|
| `store_number` | `720` | `ActionStoreWrapper_GetGeneralDetails` → `Store.Store_Number` | `StoreNumber` param in promotions + product calls |
| `user_store_id` | `"901"` | `ActionCustomerTemp_GetDetails` → `PreferredStoreId` | `UserStoreId` param in promotions-list call |

`store_number` (720) is the public-facing identifier — it matches the trailing number in the store URL (`/supermarkten/utrecht_plus_720`). This is the meaningful one for product availability: passing `StoreNumber: 720` in product/promotion requests causes the API to set `IsAvailable` per product based on stock at that specific store. All future product-fetching calls must pass this.

`user_store_id` (901) is an internal database record ID with no URL-visible form. `PreferredStoreNumber` and `PreferredStoreChannelId` on the same record are both empty — it is backend-only.

**Cart operations do not need a store ID.** The `CheckoutId` is bound to the account's preferred store server-side at checkout creation time. `ActionCheckoutItem_Add` takes only `CheckoutId`, `SKU`, `QuantityToAdd`, and `OneWelcomeUserId` — stock validation happens server-side against the associated store.

### Session state captured automatically at startup

After login + cart page navigation (no clicks), the following are known:
- `CheckoutId` — stable per user account
- `CheckoutVersion` — increments with every cart modification; always updated from API responses
- `OneWelcomeUserId` — user's identity provider UUID
- `moduleVersion` — module-level version hash
- `store_number` (720) — public store number; used in all product/promotion calls for stock filtering
- `user_store_id` ("901") — internal store record ID; used in promotions-list call and purchase history call
- `LineItemIds` for all current cart items (from response interception)
- `apiVersions` for Add/Remove/Get/Promotions/PromoDetail/OrderList/OrderDetail/PurchaseHistory — from disk cache (`~/.config/pyplus/api_versions.json`)

Order and purchase-history apiVersions are primed on first use by navigating to their respective pages (`/bestellingen`, `/order-details?OrderId=…`, `/eerder-gekochte-producten`) and intercepting the naturally-fired browser call.

### `CheckoutVersion` (optimistic locking)

The server requires the client to send the current `CheckoutVersion` with every write. The server returns the new version in the response. Client always uses the latest received version. This prevents double-adds and race conditions — a fundamental improvement over the R implementation's `Sys.sleep`-based badge polling.

---

## Python stack

| Component | Choice | Reason |
|---|---|---|
| Browser automation | **Playwright** (async) | Proper `async/await`, Chromium DevTools Protocol, request/response interception |
| HTTP client | **`page.evaluate(fetch(...))`** | Runs inside the browser page — inherits all cookies, Origin, Sec-Fetch-* headers automatically. Direct `httpx` calls return 403 due to OutSystems security checks |
| UI framework | **NiceGUI** | FastAPI + Vue/Quasar, WebSocket-based reactivity, async-native, drag-drop, modals |
| Data storage | **SQLite + SQLAlchemy 2.x ORM** (async via aiosqlite, Alembic migrations) | Replaces per-user `.rds` binary files |
| Version cache | **JSON file** on disk | `~/.config/pyplus/api_versions.json` |

### Why `page.evaluate(fetch(...))` and not `httpx`

Direct `httpx` calls return HTTP 403 even with the correct cookies and CSRF token. PLUS.nl's OutSystems backend validates `Origin`, `Referer`, and `Sec-Fetch-*` headers which only a real browser sets. Running the `fetch()` from inside the Playwright page context sets all these automatically.

---

## File structure

`plus/` is the reverse-engineered PLUS.nl client (this document's subject). `pyplus/` is the full
application built on top of it. See `README.md` and `CLAUDE.md` for the application layer.

```
new_app/
├── plus/                       # PLUS.nl integration client (reverse-engineered)
│   ├── client.py               # PlusClient: all API methods + session capture
│   ├── api.py                  # SessionState dataclass, PlusDirectClient
│   ├── models.py               # Cart, CartItem, Promotion, PromotionProduct, PromotionResult,
│   │                           #   OrderSummary, OrderDetail, OrderLineItem, PurchasedProduct
│   └── version_cache.py        # Disk cache for apiVersion hashes (all endpoints)
├── pyplus/                     # The application (config, db, ui, services, ml, jobs)
├── migrations/                 # Alembic schema versions
├── tools/migrate_rds.py        # one-time R .rds → SQLite importer
└── tests/
    ├── test_*.py               # pytest unit suite (offline)
    └── manual/                 # live-API smoke scripts (need real credentials)
```

---

## What the client provides

- Login via OAuth2 browser flow ✓
- Add N units of any SKU to remote cart — direct API, ~400ms ✓
- Remove N units of any SKU from remote cart — direct API, ~400ms ✓
- Read full cart state (items, quantities, prices, totals) ✓
- Promotions — full week, all categories, clean JSON — direct API, ~400ms ✓
- Next-week promotions (`IsNextWeekPromotions: true`) ✓
- Products behind a group deal — on-demand by slug — direct API, ~400ms ✓
- Product search at a store (`search_products_api`) ✓
- Order list — all past online orders with date, total, status — direct API, ~800ms ✓
- Order detail — full line items per order (SKU, qty, price, category) — direct API, ~400ms ✓
- Purchase history — all ever-bought products, online + in-store, deduplicated — direct API, ~2s (2 pages) ✓
- apiVersion caching — first session discovers, all subsequent sessions skip browser primes ✓
- `CheckoutVersion` tracking — atomic, no double-adds ✓
- Store/customer identity captured passively during login (no extra navigation) ✓

---

## Key numbers

| Metric | R/Chromote (old) | Python/Playwright (new) |
|---|---|---|
| Time per cart item (add) | 20–30s | ~400ms |
| 10-item basket total | ~3–5 min | ~7s (incl. login + 1 browser prime) |
| Double-add risk | Yes (badge polling race) | No (atomic `QuantityToAdd`) |
| CSS class dependency | Every operation | Login page only |
| Browser after login | Full navigation per item | Zero (after first-session primes) |
