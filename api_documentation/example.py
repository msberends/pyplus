"""
PLUS.nl API — minimal standalone example.

Demonstrates: login, read cart, add an item, search for a product.

Requirements:
    pip install playwright
    playwright install chromium

Usage:
    python example.py
"""

import asyncio
import json
import re

from playwright.async_api import async_playwright

# ── Configuration ──────────────────────────────────────────────────────────────

# Actual PLUS login credentials
EMAIL = "your@email.nl"
PASSWORD = "yourpassword"

# Your store number — visible in your PLUS store URL, e.g. /supermarkten/utrecht_plus_720
# Needed for product search; not needed for cart operations.
STORE_NUMBER = 720

# ── Constants ──────────────────────────────────────────────────────────────────

LOGIN_URL = (
    "https://aanmelden.plus.nl/plus/login/"
    "?goto=https%3A%2F%2Faanmelden.plus.nl%2Fplus%2Fauth%2Foauth2.0%2Fv1%2Fauthorize"
    "%3Fresponse_type%3Dcode%26scope%3Dopenid%2Bprofile%26client_id%3Dweb_ecop_eprod"
    "%26redirect_uri%3Dhttps%253A%252F%252Fwww.plus.nl%252FCallback"
)
SCREENSERVICES = "https://www.plus.nl/screenservices"
CHANNEL_ID = "1690b994-7511-41cc-a1bc-aacf2726f218"

# ── Session state ──────────────────────────────────────────────────────────────

# These are populated during login and used by all subsequent calls.
session = {
    "checkout_id": "",
    "checkout_version": 0,
    "onewelcome_user_id": "",
    "module_version": "",
    "api_version": "",
    "cart_add_api_version": "",
    "cart_get_api_version": "",
    "search_api_version": "",
}


# ── Network interception — captures version hashes and session IDs ─────────────

def on_request(request):
    """Intercept outgoing requests to harvest version hashes and session IDs."""
    url = request.url
    if "screenservices" not in url or request.method != "POST":
        return
    try:
        body = request.post_data_json or {}
        vi = body.get("versionInfo", {})
        mv = vi.get("moduleVersion", "")
        av = vi.get("apiVersion", "")
        if mv and not session["module_version"]:
            session["module_version"] = mv
            session["api_version"] = av
        if "ECP_Cart_CW" in url and mv:
            session["module_version"] = mv  # prefer cart module version
        if "ActionCheckoutItem_Add" in url and av and not session["cart_add_api_version"]:
            session["cart_add_api_version"] = av
        if "DataActionGetCartById" in url and av and not session["cart_get_api_version"]:
            session["cart_get_api_version"] = av
        if "DataActionGetProductListAndCategoryInfo" in url and av and not session["search_api_version"]:
            session["search_api_version"] = av
        params = body.get("inputParameters", {})
        if params.get("CheckoutId") and not session["checkout_id"]:
            session["checkout_id"] = params["CheckoutId"]
            session["checkout_version"] = params.get("CheckoutVersion", 0)
        if params.get("OneWelcomeUserId") and not session["onewelcome_user_id"]:
            session["onewelcome_user_id"] = params["OneWelcomeUserId"]
    except Exception:
        pass


async def on_response(response):
    """Intercept cart responses to keep checkout_version up to date."""
    url = response.url
    if response.status != 200:
        return
    if "DataActionGetCartById" in url or "ActionCheckoutItem_Add" in url:
        try:
            body = await response.json()
            checkout = body.get("data", {}).get("Checkout", {})
            if "Version" in checkout:
                session["checkout_version"] = checkout["Version"]
        except Exception:
            pass


# ── CSRF helper ────────────────────────────────────────────────────────────────

# Extracts the crf= token from the nr2Users cookie inside the page.
_CSRF_JS = """
    (() => {
        const map = {};
        document.cookie.split('; ').forEach(c => {
            const eq = c.indexOf('=');
            if (eq > 0) map[c.slice(0, eq)] = c.slice(eq + 1);
        });
        const nr2 = decodeURIComponent(map['nr2Users'] || '');
        const field = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
        return field.slice(field.indexOf('=') + 1);
    })()
"""


async def _post(page, path: str, payload: dict) -> dict:
    """Execute a screenservices POST from inside the browser page."""
    url = f"{SCREENSERVICES}/{path}"
    result = await page.evaluate(
        """async ([url, payload, csrfToken]) => {
            const resp = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'x-csrftoken': csrfToken,
                    'outsystems-locale': 'nl-NL',
                },
                body: JSON.stringify(payload),
                credentials: 'include',
            });
            if (!resp.ok) {
                const text = await resp.text().catch(() => '');
                throw new Error('HTTP ' + resp.status + ': ' + text.slice(0, 200));
            }
            return await resp.json();
        }""",
        [url, payload, await page.evaluate(_CSRF_JS)],
    )
    vi = result.get("versionInfo", {})
    if vi.get("hasApiVersionChanged"):
        raise RuntimeError(
            f"PLUS.nl deployed a new version — re-run to re-discover apiVersion for {path}"
        )
    return result


# ── Login ──────────────────────────────────────────────────────────────────────

async def login(page) -> None:
    """Log in to PLUS.nl via the OAuth2 browser flow (~20s)."""
    print("Navigating to login page…")
    await page.goto(LOGIN_URL)
    await page.wait_for_selector("#username", timeout=15_000)
    await page.fill("#username", EMAIL)
    await page.fill("#password", PASSWORD)
    await page.click("#loginFormUsernameAndPasswordButton")
    await page.wait_for_url("https://www.plus.nl/**", timeout=25_000)

    # Dismiss cookie consent if present
    try:
        await page.get_by_text("Weigeren", exact=True).click(timeout=3_000)
    except Exception:
        pass

    # Navigate to cart to prime checkout_id, checkout_version, and api versions
    print("Loading cart page to capture session state…")
    await page.goto("https://www.plus.nl/winkelwagen")
    await page.wait_for_load_state("networkidle", timeout=15_000)
    await asyncio.sleep(1)  # let intercepted responses settle

    print(f"  checkout_id      : {session['checkout_id'][:8]}…")
    print(f"  checkout_version : {session['checkout_version']}")
    print(f"  onewelcome_id    : {session['onewelcome_user_id'][:8]}…")
    print(f"  module_version   : {session['module_version'][:16]}…")


# ── Get cart ───────────────────────────────────────────────────────────────────

async def get_cart(page) -> dict:
    """Fetch the current cart contents."""
    if not session["cart_get_api_version"]:
        # Navigate to cart once so the browser fires DataActionGetCartById
        await page.goto("https://www.plus.nl/winkelwagen")
        await page.wait_for_load_state("networkidle", timeout=15_000)
        await asyncio.sleep(1)

    payload = {
        "versionInfo": {
            "moduleVersion": session["module_version"],
            "apiVersion": session["cart_get_api_version"] or session["api_version"],
        },
        "viewName": "MainFlow.Cart",
        "inputParameters": {"CheckoutId": session["checkout_id"]},
    }
    result = await _post(page, "ECP_Cart_CW/DataActionGetCartById", payload)
    checkout = result["data"].get("Checkout", {})
    session["checkout_version"] = checkout.get("Version", session["checkout_version"])
    return checkout


# ── Add to cart ────────────────────────────────────────────────────────────────

async def add_to_cart(page, sku: str, quantity: int = 1) -> dict:
    """Add `quantity` units of `sku` to the cart."""
    if not session["cart_add_api_version"]:
        # Navigate to search page so the browser fires ActionCheckoutItem_Add
        # when we prime the version by clicking Add once — or just navigate and
        # let the interception happen on our first programmatic call below.
        await page.goto(f"https://www.plus.nl/zoekresultaten?SearchTerm={sku}")
        await page.wait_for_load_state("networkidle", timeout=15_000)
        await asyncio.sleep(1)

    payload = {
        "versionInfo": {
            "moduleVersion": session["module_version"],
            "apiVersion": session["cart_add_api_version"] or session["api_version"],
        },
        "viewName": "MainFlow.SearchPage",
        "inputParameters": {
            "IsOrderEditMode": False,
            "CheckoutId": session["checkout_id"],
            "CheckoutVersion": session["checkout_version"],
            "OrderEditId": "",
            "SKU": sku,
            "QuantityToAdd": quantity,
            "ChannelId": CHANNEL_ID,
            "OneWelcomeUserId": session["onewelcome_user_id"],
        },
    }
    result = await _post(page, "ECP_Cart_CW/ActionCheckoutItem_Add", payload)
    checkout = result["data"]["Checkout"]
    session["checkout_version"] = checkout["Version"]
    return checkout


# ── Product search ─────────────────────────────────────────────────────────────

_SEARCH_EMPTY_ITEM = {
    "SKU": "", "Brand": "", "Name": "", "Product_Subtitle": "", "Slug": "",
    "ImageURL": "", "ImageLabel": "", "MetaTitle": "", "MetaDescription": "",
    "OriginalPrice": "0", "NewPrice": "0", "Quantity": 0, "LineItemId": "",
    "IsProductOverMajorityAge": False,
    "Logos": {
        "PLPInUpperLeft": {"List": [], "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0}},
        "PLPAboveTitle":  {"List": [], "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0}},
        "PLPBehindSizeUnit": {"List": [], "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0}},
    },
    "EAN": "", "Packging": "", "Categories": {"List": [], "EmptyListItem": {"Name": ""}},
    "IsAvailable": False, "PromotionLabel": "", "PromotionBasedLabel": "",
    "PromotionStartDate": "1900-01-01", "PromotionEndDate": "1900-01-01",
    "IsFreeDeliveryOffer": False, "IsOfflineSaleOnly": False,
    "MaxOrderLimit": 0, "CitrusAdId": "", "IsLocalItem": False,
}


def _promo_week() -> dict:
    import datetime as dt
    today = dt.date.today()
    start = today - dt.timedelta(days=(today.weekday() - 2) % 7)
    return {"FromDate": start.isoformat(), "ToDate": (start + dt.timedelta(days=6)).isoformat()}


async def search_products(page, query: str) -> list[dict]:
    """Search for products by keyword. Returns a list of product dicts."""
    if not session["search_api_version"]:
        import urllib.parse
        await page.goto(f"https://www.plus.nl/zoekresultaten?SearchTerm={urllib.parse.quote(query)}")
        await page.wait_for_load_state("networkidle", timeout=25_000)
        await asyncio.sleep(1)

    payload = {
        "versionInfo": {
            "moduleVersion": session["module_version"],
            "apiVersion": session["search_api_version"] or session["api_version"],
        },
        "viewName": "MainFlow.SearchPage",
        "screenData": {
            "variables": {
                "AppliedFiltersList": {"List": [], "EmptyListItem": {"Name": "", "Quantity": "0", "IsSelected": False, "URL": ""}},
                "LocalCategoryID": 0, "LocalCategoryName": "", "LocalCategoryParentId": 0,
                "LocalCategoryTitle": "", "IsLoadingMore": False, "IsFirstDataFetched": False,
                "ShowFilters": False, "IsShowData": False,
                "StoreNumber": STORE_NUMBER,
                "StoreChannel": CHANNEL_ID,
                "CheckoutId": session["checkout_id"],
                "IsOrderEditMode": False,
                "ProductList_All": {"List": [], "EmptyListItem": _SEARCH_EMPTY_ITEM},
                "PageNumber": 1, "SelectedSort": "", "OrderEditId": "",
                "IsListRendered": False, "IsAlreadyFetch": False, "IsPromotionBannersFetched": False,
                "Period": _promo_week(),
                "UserStoreId": "",  # optional for search
                "FilterExpandedList": {"List": [], "EmptyListItem": False},
                "ItemsInCart": {"List": []},
                "HideDummy": False,
                "OneWelcomeUserId": session["onewelcome_user_id"],
                "_oneWelcomeUserIdInDataFetchStatus": 1,
                "CategorySlug": "", "_categorySlugInDataFetchStatus": 1,
                "SearchKeyword": query, "_searchKeywordInDataFetchStatus": 1,
                "IsDesktop": True, "_isDesktopInDataFetchStatus": 1,
                "IsSearch": True, "_isSearchInDataFetchStatus": 1,
                "URLPageNumber": 1, "_uRLPageNumberInDataFetchStatus": 1,
                "FilterQueryURL": "", "_filterQueryURLInDataFetchStatus": 1,
                "IsMobile": False, "_isMobileInDataFetchStatus": 1,
                "IsTablet": False, "_isTabletInDataFetchStatus": 1,
                "Monitoring_FlowTypeId": 2, "_monitoring_FlowTypeIdInDataFetchStatus": 1,
                "IsCustomerUnderAge": False, "_isCustomerUnderAgeInDataFetchStatus": 1,
            }
        },
    }
    result = await _post(
        page,
        "ECP_Composition_CW/ProductLists/PLP_Content/DataActionGetProductListAndCategoryInfo",
        payload,
    )
    data = result.get("data", {})
    raw = data.get("ProductList_All", {}).get("List", [])
    products = []
    for item in raw:
        p = item.get("PLP_Str", item)
        if not p.get("SKU"):
            continue
        products.append({
            "sku": p.get("SKU", ""),
            "name": p.get("Name", ""),
            "subtitle": p.get("Product_Subtitle", ""),
            "brand": p.get("Brand", ""),
            "price": p.get("OriginalPrice", "0"),
            "is_available": p.get("IsAvailable", False),
            "url": f"https://www.plus.nl/product/{p['Slug']}" if p.get("Slug") else "",
        })
    return products


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="nl-NL",
            timezone_id="Europe/Amsterdam",
        )
        page = await context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        # 1. Login
        print("\n=== Login ===")
        await login(page)

        # 2. Read cart
        print("\n=== Cart ===")
        cart = await get_cart(page)
        items = cart.get("LineItemList", {}).get("List", [])
        print(f"{len(items)} item(s) in cart:")
        for item in items:
            print(f"  {item['Quantity']}x  {item['Name']:<40}  €{item['Price']}")
        receipt = cart.get("Receipt", {})
        print(f"Total: €{receipt.get('Price', '?')}")

        # 3. Add an item (PLUS Halfvolle Melk, SKU 957806 — change to any valid SKU)
        print("\n=== Add to cart ===")
        sku_to_add = "957806"
        checkout = await add_to_cart(page, sku_to_add, quantity=1)
        new_count = len(checkout.get("LineItemList", {}).get("List", []))
        print(f"Added SKU {sku_to_add} — cart now has {new_count} line item(s), "
              f"version={checkout['Version']}")

        # 4. Search for a product
        print("\n=== Search ===")
        results = await search_products(page, "melk")
        print(f"Found {len(results)} result(s) for 'melk':")
        for p in results[:5]:
            available = "✓" if p["is_available"] else "✗"
            print(f"  [{available}] {p['sku']}  {p['name']} {p['subtitle']}  €{p['price']}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
