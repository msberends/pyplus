# PLUS.nl Unofficial API Documentation

PLUS.nl runs on **OutSystems**, a low-code platform. There is no public API. This document describes
the internal `screenservices` endpoints reverse-engineered from the PLUS.nl web frontend.

> **Status:** Accurate as of mid-2026. PLUS.nl can change these endpoints without notice.
> The version-invalidation mechanism (see §3) makes breakage detectable and recoverable.

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Authentication](#2-authentication)
3. [Session Tokens & Version Hashes](#3-session-tokens--version-hashes)
4. [Common Request Structure](#4-common-request-structure)
5. [Common Headers](#5-common-headers)
6. [Endpoints](#6-endpoints)
   - [Cart — Add Item](#61-cart--add-item)
   - [Cart — Remove Item](#62-cart--remove-item)
   - [Cart — Read](#63-cart--read)
   - [Promotions — Current/Next Week](#64-promotions--currentnext-week)
   - [Promotions — Group Deal Products](#65-promotions--group-deal-products)
   - [Order History — List](#66-order-history--list)
   - [Order History — Detail](#67-order-history--detail)
   - [Purchase History (Ever Bought)](#68-purchase-history-ever-bought)
   - [Product Search / Catalogue](#69-product-search--catalogue)
   - [Menu Categories (Product Group Order)](#610-menu-categories-product-group-order)
7. [Response Models](#7-response-models)
8. [Store Identifiers](#8-store-identifiers)
9. [Error Handling](#9-error-handling)
10. [Known Constraints](#10-known-constraints)

---

## 1. Platform Overview

All data calls are `POST` requests to:

```
https://www.plus.nl/screenservices/<Module>/<Flow>/<Screen>/<Action>
```

The frontend is a React SPA that calls OutSystems-generated `screenservices` endpoints. Key
properties of this platform:

- Every request body carries `versionInfo` with **action-specific hashes** baked into the compiled
  JavaScript. The wrong hash causes a silent failure — the server returns an empty/unavailable
  response with `hasApiVersionChanged: true`, not an HTTP error.
- Every write operation must send the current `CheckoutVersion` integer (optimistic locking).
- CSRF protection uses the `crf=` field from the `nr2Users` cookie, sent as `x-csrftoken`.
- Direct HTTP calls (with cookies copied from the browser) return **HTTP 403**. The server validates
  `Origin`, `Referer`, and `Sec-Fetch-*` headers which only a real browser sets. All calls must be
  executed inside the Playwright page context via `page.evaluate(fetch(...))`.

---

## 2. Authentication

### OAuth2 Login Flow

Login goes through a separate identity provider at `aanmelden.plus.nl`. There is no API-level
authentication — a real browser performing the full OAuth2 redirect is required.

**Login URL:**
```
https://aanmelden.plus.nl/plus/login/
  ?goto=https%3A%2F%2Faanmelden.plus.nl%2Fplus%2Fauth%2Foauth2.0%2Fv1%2Fauthorize
  %3Fresponse_type%3Dcode
  %26scope%3Dopenid%2Bprofile
  %26client_id%3Dweb_ecop_eprod
  %26redirect_uri%3Dhttps%253A%252F%252Fwww.plus.nl%252FCallback
```

Parameters:
- `client_id=web_ecop_eprod` — the PLUS.nl web app identifier (stable)
- `redirect_uri=https://www.plus.nl/Callback` — double-URL-encoded in the goto parameter

**Browser flow:**
1. Navigate to the login URL
2. Fill `#username` (email) and `#password`
3. Click `#loginFormUsernameAndPasswordButton`
4. Wait for redirect to `https://www.plus.nl/**`
5. Dismiss cookie consent dialog if present (`aria-label="De cookies van PLUS"`, click "Weigeren")
6. Confirm login via `.gtm-account-options .popover-top-label span` selector

**Timing:** ~20 seconds total (OAuth2 redirect chain).

### Session Cookies

After a successful login, the browser holds session cookies including `nr2Users`. These cookies are
what authenticate subsequent API calls. They are passed automatically via `credentials: 'include'`
in `fetch()` calls executed inside the browser page.

### CSRF Token

Every POST request must include the `x-csrftoken` header. The value is extracted from the
`nr2Users` cookie at call time:

```javascript
const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
const crfField = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
const csrfToken = crfField.slice(crfField.indexOf('=') + 1);
```

---

## 3. Session Tokens & Version Hashes

### What Must Be Captured

After login + cart page navigation (no extra clicks), the following values are captured passively
by intercepting browser network requests:

| Field | Type | Source | Description |
|---|---|---|---|
| `checkout_id` | string (UUID) | Any cart request body | Stable per account; the cart identifier |
| `checkout_version` | integer | Cart API response `Checkout.Version` | Increments on every write; must always be current |
| `onewelcome_user_id` | string (UUID) | Any cart/account request body | User identity for all account-scoped calls |
| `module_version` | string (hash) | `versionInfo.moduleVersion` in any request | Module-level version; used as fallback |
| `cart_module_version` | string (hash) | `versionInfo.moduleVersion` in ECP_Cart_CW requests | Cart-specific module version |
| `store_number` | integer | `ActionStoreWrapper_GetGeneralDetails` response | Public store number, e.g. `720` |
| `user_store_id` | string | `ActionCustomerTemp_GetDetails` response | Internal store record ID, e.g. `"901"` |

### Action-Specific API Version Hashes

Each OutSystems action has its own `apiVersion` hash. These are baked into PLUS.nl's compiled
JavaScript and are stable between deployments. They are discovered once by intercepting a live
browser request and then cached to disk at `~/.config/pyplus/api_versions.json`.

| Field | Discovered from |
|---|---|
| `cart_add_api_version` | `ActionCheckoutItem_Add` request |
| `cart_remove_api_version` | `ActionCheckoutItem_Remove` request |
| `cart_get_api_version` | `DataActionGetCartById` request |
| `promotions_api_version` | `DataActionGetPromotionList_Optimization` request |
| `promo_detail_api_version` | `DataActionPromotionOfferDetail_Get` request |
| `purchase_history_api_version` | `RecentlyBoughtProducts/DataActionGetProducts` request |
| `order_list_api_version` | `OrdersContent/DataActionGetCustomerDetails` request |
| `order_detail_api_version` | `OrderDetailsContent/DataActionGetOrderDetails` request |
| `search_api_version` | `DataActionGetProductListAndCategoryInfo` request |

**First-time discovery:** For Add and Remove, the browser must perform the action once (navigate to
a search page, click Add; navigate to cart, open quantity slider, click Remove). All other versions
are discovered by navigating to their respective page and intercepting the naturally-fired call.

**Reuse:** Once discovered, versions are loaded from the disk cache on every subsequent session. The
version for Add/Remove is only re-discovered when PLUS.nl deploys (detected via
`hasApiVersionChanged: true` in any response).

### Token Reuse Pattern

```
Session start
  └─ Load cached api_versions.json                   # fills action-specific hashes
  └─ Login (browser, ~20s)                           # populates session cookies
  └─ Navigate to cart page                           # intercepts: checkout_id,
                                                     #   checkout_version, cart versions,
                                                     #   store_number, user_store_id

Subsequent calls (same session)
  └─ page.evaluate(fetch(...))                       # inherits cookies, CSRF, headers
  └─ Update checkout_version from every response     # mandatory for writes

Session end
  └─ Save any newly discovered api_versions          # to disk cache
```

---

## 4. Common Request Structure

Every `screenservices` request is a JSON POST body with this shape:

```json
{
  "versionInfo": {
    "moduleVersion": "<module_version>",
    "apiVersion": "<action_specific_api_version>"
  },
  "viewName": "<OutSystems screen name>",
  "inputParameters": { ... }   // for simple actions (cart add/remove/get)
}
```

Or for screen data actions (promotions, orders, history, search):

```json
{
  "versionInfo": {
    "moduleVersion": "<module_version>",
    "apiVersion": "<action_specific_api_version>"
  },
  "viewName": "<OutSystems screen name>",
  "screenData": {
    "variables": { ... }       // full screen variable set — must match browser exactly
  }
}
```

> **Critical:** Screen data actions (`screenData.variables`) require the full variable set,
> including `EmptyListItem` type schemas and `_*InDataFetchStatus` flags. Omitting any field causes
> the server to return all items as unavailable (`IsAvailable: false`, `Quantity: 0`) with no error.

---

## 5. Common Headers

All requests require:

```
Content-Type: application/json
x-csrftoken: <value from nr2Users cookie crf= field>
outsystems-locale: nl-NL
```

And must be sent from inside the browser page context (to inherit `Origin`, `Referer`,
`Sec-Fetch-*` headers automatically).

---

## 6. Endpoints

### 6.1 Cart — Add Item

```
POST https://www.plus.nl/screenservices/ECP_Cart_CW/ActionCheckoutItem_Add
```

**viewName:** `MainFlow.SearchPage`

**inputParameters:**

| Field | Type | Required | Description |
|---|---|---|---|
| `CheckoutId` | string (UUID) | yes | The account's cart identifier |
| `CheckoutVersion` | integer | yes | Current version; must be up to date |
| `SKU` | string | yes | Product SKU, e.g. `"957806"` |
| `QuantityToAdd` | integer | yes | Number of units to add (can be >1 in one call) |
| `OneWelcomeUserId` | string (UUID) | yes | User identity |
| `ChannelId` | string (UUID) | yes | Web channel ID: `"1690b994-7511-41cc-a1bc-aacf2726f218"` |
| `IsOrderEditMode` | boolean | yes | Always `false` for normal cart operations |
| `OrderEditId` | string | yes | Always `""` for normal cart operations |

**Example body:**
```json
{
  "versionInfo": {
    "moduleVersion": "<cart_module_version>",
    "apiVersion": "<cart_add_api_version>"
  },
  "viewName": "MainFlow.SearchPage",
  "inputParameters": {
    "IsOrderEditMode": false,
    "CheckoutId": "<checkout_id>",
    "CheckoutVersion": 42,
    "OrderEditId": "",
    "SKU": "957806",
    "QuantityToAdd": 2,
    "ChannelId": "1690b994-7511-41cc-a1bc-aacf2726f218",
    "OneWelcomeUserId": "<onewelcome_user_id>"
  }
}
```

**Response:** `{ "data": { "Checkout": { "Version": <new_version>, "LineItemList": { "List": [...] }, "Receipt": {...} } } }`

Update `checkout_version` from `data.Checkout.Version` after every call.

---

### 6.2 Cart — Remove Item

```
POST https://www.plus.nl/screenservices/ECP_Cart_CW/ActionCheckoutItem_Remove
```

**viewName:** `MainFlow.Cart`

**inputParameters:**

| Field | Type | Required | Description |
|---|---|---|---|
| `CheckoutId` | string (UUID) | yes | Cart identifier |
| `CheckoutVersion` | integer | yes | Current version |
| `SKU` | string | yes | Product SKU |
| `LineItemId` | string (UUID) | yes | Server-assigned per-cart-item ID (see below) |
| `QuantityToRemove` | integer | yes | Units to remove |
| `OneWelcomeUserId` | string (UUID) | yes | User identity |
| `ChannelId` | string (UUID) | yes | `"1690b994-7511-41cc-a1bc-aacf2726f218"` |
| `IsOrderEditMode` | boolean | yes | Always `false` |
| `OrderEditId` | string | yes | Always `""` |

**LineItemId:** A UUID assigned by the server when an item is added. It is returned in every cart
response under `Checkout.LineItemList.List[].LineItemId`. Must be tracked per SKU. It changes when
an item is removed and re-added.

**Response:** Same shape as Add — `{ "data": { "Checkout": { ... } } }`.

---

### 6.3 Cart — Read

```
POST https://www.plus.nl/screenservices/ECP_Cart_CW/DataActionGetCartById
```

**viewName:** `MainFlow.Cart`

**inputParameters:**

| Field | Type | Required | Description |
|---|---|---|---|
| `CheckoutId` | string (UUID) | yes | Cart identifier |

**Example body:**
```json
{
  "versionInfo": {
    "moduleVersion": "<cart_module_version>",
    "apiVersion": "<cart_get_api_version>"
  },
  "viewName": "MainFlow.Cart",
  "inputParameters": {
    "CheckoutId": "<checkout_id>"
  }
}
```

**Response structure:**
```json
{
  "data": {
    "Checkout": {
      "Version": 42,
      "LineItemList": {
        "List": [
          {
            "SKU": "957806",
            "Name": "PLUS Melk Halfvol",
            "Subtitle": "Per 1 L",
            "Price": "1.09",
            "Quantity": 2,
            "LineItemId": "<uuid>",
            "ImageURL": "//static.plus.nl/..."
          }
        ]
      },
      "Receipt": {
        "Price": "18.50",
        "DiscountedPrice": "0.46",
        "DepositFeeCosts": "1.75"
      }
    }
  }
}
```

`Receipt.Price` is the final total including deposit (`DepositFeeCosts`).
`Receipt.DiscountedPrice` is the promotional discount (korting) already deducted from `Price`.

---

### 6.4 Promotions — Current/Next Week

```
POST https://www.plus.nl/screenservices/ECP_Composition_CW/Promotions/Promotion_LP_Content_TF_Optimization/DataActionGetPromotionList_Optimization
```

**viewName:** `MainFlow.Promotions`

Uses `screenData.variables` (not `inputParameters`).

**Key variables:**

| Field | Type | Required | Description |
|---|---|---|---|
| `StoreNumber` | integer | yes | Public store number, e.g. `720` |
| `UserStoreId` | string | yes | Internal store record ID, e.g. `"901"` |
| `OneWelcomeUserId` | string (UUID) | yes | User identity |
| `StoreChannel` | string (UUID) | yes | `"1690b994-7511-41cc-a1bc-aacf2726f218"` |
| `IsNextWeekPromotions` | boolean | yes | `false` = current week, `true` = next week |
| `ItemExistsInCart` | object | yes | `{ "List": [{ "LineItemId": "...", "SKU": "...", "Quantity": 0 }] }` — current cart items |
| `LocalPromotionList` | object | yes | `{ "List": [], "EmptyListItem": <_PROMO_EMPTY_ITEM> }` — see note |
| `PromotionPeriodId` | integer | yes | `1` |
| `IsCustomerUnderAge` | boolean | yes | `false` |
| `IsTimetraveler` | boolean | yes | `false` |
| `IsDesktop` / `IsTablet` / `IsPhone` | boolean | yes | `true` / `false` / `false` |

> **Note:** `LocalPromotionList.EmptyListItem` must be the full OutSystems type schema constant
> (`_PROMO_EMPTY_ITEM` in `client.py`). It defines the expected return type; sending a simplified
> version causes the server to silently return no promotions.

**Response:** `data.PromotionOfferList.List[]` — array of category sections, each containing
`Category.CategoryId`, `Category.CategoryLabel`, and `Category.Offers.List[]` with individual
promotion offers.

Each offer includes: `Slug`, `Brand`, `Name`, `Example` (subtitle), `Variant`, `DisplayInfo_Label`
(deal label e.g. "1+1 GRATIS"), `NewPrice`, `PriceOriginal_Lowest`, `StartDate`, `EndDate`,
`ImageURL`, `IsFreeDeliveryOffer`, `IsSingleProduct`, `Product_SKU` (only when `IsSingleProduct`).

Also at top level: `data.PromotionPeriod.FromDate`, `data.PromotionPeriod.ToDate`,
`data.IsNextWeekPublished`.

---

### 6.5 Promotions — Group Deal Products

```
POST https://www.plus.nl/screenservices/ECP_Promotion_CW/PromotionDetailsFlow/PromotionOffer_DP_Content/DataActionPromotionOfferDetail_Get
```

**viewName:** `MainFlow.Promotions`

Only relevant for promotions where `IsSingleProduct: false`. Returns the individual products
qualifying for a group deal (e.g. "1+1 GRATIS — choose any 2 of 25 products").

**Key screenData.variables:**

| Field | Type | Required | Description |
|---|---|---|---|
| `PromotionOfferId` | string | yes | The promotion slug, e.g. `"4431-96"` |
| `StoreNumber` | integer | yes | Public store number |
| `CheckoutId` | string (UUID) | yes | Cart identifier |
| `StoreChannelD` | string (UUID) | yes | Note: `StoreChannelD` (trailing **D**), not `StoreChannel` |
| `LineItemRecList` | object | yes | `{ "List": [{ "LineItemId": "...", "SKU": "...", "Quantity": 0 }] }` |
| `OneWelcomeUserId` | string (UUID) | yes | User identity |
| `IsDesktop` / `IsTablet` / `IsPhone` | boolean | yes | `true` / `false` / `false` |

**Response:** `data.PromotionOfferDetail.ProductList.List[]` — each item has a `PLP_Str` object
with `SKU`, `Brand`, `Name`, `Product_Subtitle`, `Slug`, `ImageURL`, `NewPrice`, `IsAvailable`,
`MaxOrderLimit`; and outer fields `Price_Original`, `DisplayInfo_Label`.

---

### 6.6 Order History — List

```
POST https://www.plus.nl/screenservices/ECP_Customer_CW/Account/OrdersContent/DataActionGetCustomerDetails
```

> Note: The action name is misleading — this returns order history, not a customer profile.

**viewName:** `AccountFlow.OrdersOverview`

> **Critical:** `viewName` must be `AccountFlow.OrdersOverview`, not `MainFlow.*`. Wrong value
> silently returns all items as unavailable.

**Key screenData.variables:**

| Field | Type | Required | Description |
|---|---|---|---|
| `OneWelcomeUserId` | string (UUID) | yes | User identity |
| `QueryOffset` | integer | yes | Pagination offset; `0` for first page |
| `CurrDateTime` | string | yes | Current UTC timestamp: `"2026-07-04T12:00:00.000Z"` |
| `IsDesktop` / `IsTablet` | boolean | yes | `true` / `false` |
| `IsToOverview` | boolean | yes | `false` |
| `IsToShowSideMenu` | boolean | yes | `true` |
| `Orders_Active` / `Orders_Previous` | object | yes | `{ "List": [], "EmptyListItem": <_ORDER_EMPTY_ITEM> }` |
| `IsLoadingMore` | boolean | yes | `true` |
| `IsShowData` | boolean | yes | `false` |
| `HasMoreItemsToLoad` | boolean | yes | `false` |

**Response:** Two lists at `data.Orders_Struct_Active` (upcoming orders) and
`data.Orders_Struct_Previous` (past orders). Each order:

| Field | Description |
|---|---|
| `Order_Id` | UUID — used in order detail calls and `/order-details?OrderId=` URL |
| `Order_Number` | Human-readable order number |
| `Order_DeliveryDate` | `"2026-03-16"` |
| `Order_DeliveryStartTime` / `Order_DeliveryEndTime` | `"10:00"` / `"12:00"` |
| `Order_TotalPrice` | `"47.82"` |
| `DeliveryType_ServiceStatusLabel` | `"Bezorgd"`, `"Opgehaald"`, `"In behandeling"` |
| `BusinessInterfaceId` | `"Web"` or `"App"` |

---

### 6.7 Order History — Detail

```
POST https://www.plus.nl/screenservices/ECP_Customer_CW/CustomerDetails/OrderDetailsContent/DataActionGetOrderDetails
```

**viewName:** `AccountFlow.OrderDetail`

**Key screenData.variables:**

| Field | Type | Required | Description |
|---|---|---|---|
| `OrderId` | string (UUID) | yes | From `Order_Id` in the order list |
| `OneWelcomeUserId` | string (UUID) | yes | User identity |
| `ExternalChannelId` | string (UUID) | yes | `"1690b994-7511-41cc-a1bc-aacf2726f218"` |
| `CurrDateTime` | string | yes | Current UTC timestamp |
| `Locale` | string | yes | `"nl-NL"` |
| `IsDesktop` / `IsTablet` / `IsPhone` | boolean | yes | `true` / `false` / `false` |
| `IsToShowSideMenu` | boolean | yes | `true` |
| `IsOrderEditMode` / `IsPunchOutSession` | boolean | yes | `false` / `false` |
| `ShowChangeOrderPopUp` / `ShowCancelOrderPopup` | boolean | yes | `false` / `false` |
| `VoucherJSON` / `CurrentCartId` | string | yes | `""` / `""` |

**Response:** `data.OrderHistoryDetail` with:
- `Order_Id`, `Order_Number`, `Order_DeliveryDate`, `Order_StoreName`, `DeliveryType_ServiceStatusLabel`, `Order_ShippingAddress`
- `AvailableItemList.List[]` — items that were delivered
- `UnavailableItemList.List[]` — items that could not be delivered

Each line item: `SKU`, `Name`, `Subtitle`, `Slug`, `Quantity`, `Price`, `Category`, `ImageURL`.

---

### 6.8 Purchase History (Ever Bought)

```
POST https://www.plus.nl/screenservices/ECP_Customer_CW/Account/RecentlyBoughtProducts/DataActionGetProducts
```

Returns all products ever purchased — both online orders and in-store purchases made with the
account QR code. No purchase dates are available at this level; use [Order Detail](#67-order-history--detail)
for dated online orders.

**viewName:** `AccountFlow.RecentlyBoughtProducts`

**Key screenData.variables:**

| Field | Type | Required | Description |
|---|---|---|---|
| `OneWelcomeUserId` | string (UUID) | yes | User identity |
| `UserStoreChannelId` | string (UUID) | yes | `"1690b994-7511-41cc-a1bc-aacf2726f218"` |
| `UserStoreId` | string | yes | Internal store record ID, e.g. `"901"` |
| `CurrentPageNumber` | integer | yes | Page number (1-based); server returns 36 per page |
| `NumberOfProductsPerPage` | integer | yes | `36` |
| `Period` | object | yes | `{ "FromDate": "2026-06-30", "ToDate": "2026-07-06" }` — **ignored by server**; any date range returns full all-time history |
| `FromTime` | string | yes | Current time `"HH:MM:SS"` |
| `CheckoutOrderInfo` | object | yes | `{ "CheckoutId": "...", "OrderEditId": "", "IsOrderEditMode": false }` |
| `ProductList` | object | yes | `{ "List": [], "EmptyListItem": <_PURCHASE_HISTORY_EMPTY_ITEM> }` |
| `IsUnderAge` / `IsInitialDataFetched` | boolean | yes | `false` / `false` |
| `IsDesktop` / `IsTablet` / `IsPhone` | boolean | yes | `true` / `false` / `false` |

**Pagination:** Repeat with `CurrentPageNumber` = 1, 2, … until a page returns fewer items than
`NumberOfProductsPerPage`. The average account returns ~70 products across 2 pages.

**Response:** `data.Products.List[]` — each product: `SKU`, `Brand`, `Name`, `Product_Subtitle`,
`Slug`, `ImageURL`, `OriginalPrice`, `IsAvailable`, `Categories.List[].Name`.

---

### 6.9 Product Search / Catalogue

```
POST https://www.plus.nl/screenservices/ECP_Composition_CW/ProductLists/PLP_Content/DataActionGetProductListAndCategoryInfo
```

Used for both keyword search and full catalogue download (empty `SearchKeyword` returns all products,
~11k items across ~920 pages of 12).

**viewName:** `MainFlow.SearchPage`

**Key screenData.variables:**

| Field | Type | Required | Description |
|---|---|---|---|
| `SearchKeyword` | string | yes | Search term; `""` for full catalogue |
| `IsSearch` | boolean | yes | `true` for search, also `true` for catalogue crawl |
| `StoreNumber` | integer | yes | Public store number; determines `IsAvailable` per product |
| `StoreChannel` | string (UUID) | yes | `"1690b994-7511-41cc-a1bc-aacf2726f218"` |
| `CheckoutId` | string (UUID) | yes | Cart identifier |
| `UserStoreId` | string | yes | Internal store record ID |
| `OneWelcomeUserId` | string (UUID) | yes | User identity |
| `PageNumber` | integer | yes | Page number (1-based) |
| `URLPageNumber` | integer | yes | Same value as `PageNumber` |
| `Period` | object | yes | Current promo week `{ "FromDate": "...", "ToDate": "..." }` |
| `IsDesktop` / `IsTablet` / `IsPhone` / `IsMobile` | boolean | yes | `true` / `false` / `false` / `false` |
| `IsLoadingMore` | boolean | yes | `false` for page 1, `true` for subsequent pages |
| `IsCustomerUnderAge` | boolean | yes | `false` |
| `Monitoring_FlowTypeId` | integer | yes | `2` |
| `SelectedSort` / `CategorySlug` / `FilterQueryURL` / `OrderEditId` | string | yes | All `""` |
| `ProductList_All` | object | yes | `{ "List": [], "EmptyListItem": <_SEARCH_EMPTY_ITEM> }` |
| `AppliedFiltersList` | object | yes | `{ "List": [], "EmptyListItem": { "Name": "", "Quantity": "0", "IsSelected": false, "URL": "" } }` |
| `FilterExpandedList` | object | yes | `{ "List": [], "EmptyListItem": false }` |
| `ItemsInCart` | object | yes | `{ "List": [] }` |

> **Note:** The search term field is `SearchKeyword` (not `SearchTerm`). Using the wrong name causes
> the server to return 12 unavailable skeleton rows.

**Response:**
- `data.ProductList_All.List[]` — products (each wrapped in a `PLP_Str` sub-object)
- `data.TotalPages` — total page count (from page 1 response only)
- `data.TotalNumberItems` — total product count

Each product (inside `PLP_Str`): `SKU`, `Brand`, `Name`, `Product_Subtitle`, `Slug`, `ImageURL`,
`OriginalPrice`, `NewPrice`, `IsAvailable`, `Quantity` (cart quantity), `LineItemId`,
`PromotionLabel`, `PromotionStartDate`, `PromotionEndDate`, `EAN`, `MaxOrderLimit`,
`Categories.List[].Name`.

---

### 6.10 Menu Categories (Product Group Order)

```
POST https://www.plus.nl/screenservices/ECP_Product_CW/Categories/CategoryList_TF/DataActionGetMenuCategories
```

Returns PLUS's own category taxonomy — the same order shown when expanding Menu → Producten on
plus.nl. Fires automatically on a plain `https://www.plus.nl/` homepage load; no menu interaction
is needed to trigger it. Global data — not store- or user-scoped, the taxonomy and `SortOrder` are
identical for every shopper — so it does not need per-store refresh like product/promotion data.

**viewName:** `MainFlow.Home`

**Key screenData.variables:**

| Field | Type | Required | Description |
|---|---|---|---|
| `UserPreferredStoreId` | string | yes | Internal store record ID (`user_store_id`) |
| `OneWelcomeUserId` | string (UUID) | yes | User identity |
| `ParentsListLocal` | object | yes | `{ "List": [], "EmptyListItem": <category schema> }` |
| `CategoriesListLocal` | object | yes | `{ "List": [], "EmptyListItem": { "ImgHasError": false, "ShowImage": false, "IntervalID": 0, "Category": <category schema> } }` |
| `Screen_Categories` | object | yes | `{ "List": [], "EmptyListItem": { "Category": <category schema> } }` |
| `Screen_AncestorRecList` | object | yes | `{ "List": [], "EmptyListItem": { "Name": "", "Slug": "", "Order": 0 } }` |
| `IsDataPrepared` / `IsExpanded` / `IsPageSearch` | boolean | yes | `false` |
| `OriginalCategoryId` / `CategoryId` / `ParentId` / `TimeoutId` | integer | yes | `0` |
| `Category1` / `Category2` / `Category3` / `CategoryName` | string | yes | `""` |
| `PromoImgURL` / `B2BExcludedCategories` | string | yes | `""` (verified live — a blank `PromoImgURL` still returns full, correct data) |
| `ApplyShowMoreOption` | boolean | yes | `false` |

The `<category schema>` `EmptyListItem` shape: `{ "Name": "", "ExternalId": 0, "ImageURL": "", "ImageLabel": "", "HasChild": false, "ParentName": "", "ParentExternalId": 0, "SortOrder": "0", "Slug": "", "IsSeasonal": false }`.

**Response:**
- `data.CategoriesJson` — a **JSON string** (not a nested object), decode with `json.loads` first.
  Each entry is `{"Category_str": {...}}` wrapping the fields below (~589 categories).

Per-category fields: `Name`, `ExternalId`, `ParentName`, `ParentExternalId` (both **absent** — not
`null` — for top-level categories), `SortOrder` (float; absent for the synthetic "Aanbiedingen"
entry, which is always first in the real menu), `HasChild`, `Slug`, `ImageURL`, `ImageLabel`,
`IsSeasonal` (present in the schema but empirically never populated — seasonal categories like
"BBQ assortiment" aren't flagged, they just appear/reorder/disappear via `SortOrder` changes over
time, which is why any consumer of this data should treat it as a periodically-refreshed cache, not
a static snapshot).

Top-level categories (entries with no `ParentExternalId` key), sorted by `SortOrder`, reproduce
PLUS's real Menu → Producten order exactly (verified against the live site):

```
Aanbiedingen, BBQ assortiment, Aardappelen/groente/fruit, Verse kant-en-klaarmaaltijden,
Vlees/kip/vis/vega, Kaas/vleeswaren/tapas, Zuivel/eieren/boter, Brood/gebak/bakproducten,
Ontbijtgranen/broodbeleg/tussendoor, Frisdrank/sappen/koffie/thee, Wijn/bier/sterke drank,
Pasta/rijst/internationale keuken, Soepen/conserven/sauzen/smaakmakers,
Snoep/koek/chocolade/chips/noten, Diepvries, Baby/drogisterij, Bewuste voeding, Huishouden,
Wonen/bloemen/service, Huisdier
```

---

## 7. Response Models

### Checkout (cart write/read responses)

```
Checkout
├── Version: integer                   # always update your local copy
├── LineItemList.List[]
│   ├── SKU: string
│   ├── Name: string
│   ├── Subtitle: string
│   ├── Price: string (decimal)
│   ├── Quantity: integer
│   ├── LineItemId: string (UUID)
│   └── ImageURL: string               # may be protocol-relative ("//...")
└── Receipt
    ├── Price: string                  # final total incl. deposit
    ├── DiscountedPrice: string        # promotional discount already applied
    └── DepositFeeCosts: string        # statiegeld included in Price
```

### versionInfo in every response

```
versionInfo
├── hasApiVersionChanged: boolean      # true = stale hash; wipe cache, re-discover
└── hasModuleVersionChanged: boolean   # true = module redeployed; re-login
```

---

## 8. Store Identifiers

PLUS uses two distinct store identifiers. Both are captured passively during login by intercepting
`ActionStoreWrapper_GetGeneralDetails` and `ActionCustomerTemp_GetDetails` responses.

| Field | Example | Source | Used in |
|---|---|---|---|
| `store_number` | `720` | `Store.Store_Number` | `StoreNumber` in promotions, product search, purchase history |
| `user_store_id` | `"901"` | `CustomerTempDetailsR.PreferredStoreId` | `UserStoreId` in promotions list, purchase history |

`store_number` is the public identifier (matches the trailing number in store URLs).
Passing it in product/promotion requests causes the server to set `IsAvailable` based on stock at
that specific store.

`user_store_id` is an internal database record ID with no URL-visible form. It is backend-only.

**Cart operations do not need a store ID.** The `CheckoutId` is bound to the account's preferred
store server-side.

---

## 9. Error Handling

### API Version Changed

When `response.versionInfo.hasApiVersionChanged` is `true`:
1. The response data is empty or all-unavailable — do not process it
2. Clear the affected cached api_version(s)
3. Re-discover by navigating to the relevant page and intercepting the natural browser call
4. Retry

### CheckoutVersion Mismatch

If the cart returns an unexpected state, always trust the server's returned `Version` and update
your local copy. Never assume a version.

### HTTP 403

Caused by calling the `screenservices` endpoints directly with `httpx` (or any HTTP client outside
the browser context). Solution: execute all calls via `page.evaluate(fetch(...))` inside the active
Playwright page.

---

## 10. Known Constraints

- **No public API.** These endpoints are internal OutSystems scaffolding. They can change without
  notice when PLUS.nl deploys a new version.
- **Browser required for login.** The OAuth2 flow at `aanmelden.plus.nl` cannot be automated
  without a real browser. All post-login calls are direct API calls (~200–400ms each).
- **`screenData` must be complete.** Partial payloads cause silent failures (all items unavailable),
  not HTTP errors. The `EmptyListItem` type schemas embedded in list variables are load-bearing.
- **`viewName` is routing.** The wrong `viewName` (e.g. `MainFlow.*` instead of `AccountFlow.*`
  for order/history endpoints) causes silent failures.
- **`CheckoutVersion` is mandatory.** Every cart write must send the current version. The server
  uses this for optimistic locking; a stale version causes the write to fail or duplicate.
- **`LineItemId` is required for removal.** It is not derivable from the SKU alone; it must be
  captured from a cart read or add response.
- **Promotions `EmptyListItem` is ~150 lines.** The full `_PROMO_EMPTY_ITEM` schema must be sent
  verbatim in `LocalPromotionList.EmptyListItem`. See `plus/client.py` for the exact constant.
- **Product search page size is server-controlled.** The `NumberOfProductsPerPage` field in the
  search payload is ignored; the server fixes the page at 12 items.
- **Menu category order isn't stable long-term.** `SortOrder` values (§6.10) shift as PLUS adds,
  removes, or reorders categories (e.g. seasonal ones like "BBQ assortiment") — there's no flag
  distinguishing seasonal from permanent categories, so this data must be refreshed periodically
  rather than cached indefinitely or hardcoded.
