"""
PLUS.nl async client.

Uses Playwright for login (OAuth2 browser flow) and cart operations.
Intercepts network requests during the session to discover direct REST API
endpoints — printed at the end of each run so they can be hardcoded later
to replace browser automation entirely.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from . import version_cache
from .api import SessionState
from .models import (
    Cart,
    CartItem,
    OrderDetail,
    OrderLineItem,
    OrderSummary,
    Product,
    Promotion,
    PromotionProduct,
    PromotionResult,
    PurchasedProduct,
)

log = logging.getLogger(__name__)

_PROMOTIONS_URL = (
    "https://www.plus.nl/screenservices/ECP_Composition_CW/Promotions"
    "/Promotion_LP_Content_TF_Optimization/DataActionGetPromotionList_Optimization"
)
_CHANNEL_ID = "1690b994-7511-41cc-a1bc-aacf2726f218"

# OutSystems type schema for the LocalPromotionList screen variable.
# Must be sent verbatim so the server knows the expected return type.
_PROMO_EMPTY_ITEM = {
    "ProductPromotionBanner": {
        "InternalTitle": "",
        "Subtitle": "",
        "Title": "",
        "AnchorLinkTitle": "",
        "Cta": {
            "InternalTitle": "",
            "Link": {"Title": "", "Url": "", "AltText": "", "IsPdf": False},
        },
        "BackgroundColorClassName": "",
        "BannerImageNoProducts": {"AltText": ""},
        "BannerImageWithProducts": {"AltText": ""},
        "Productspromotions": {"List": [], "EmptyListItem": ""},
        "ProductPromotionTiles": {
            "List": [],
            "EmptyListItem": {
                "PromotionId": "",
                "OfferId": "",
                "ProductName": "",
                "PromotionLabel": "",
                "PromotionBasedLabel": "",
                "Subtitle": "",
                "Brand": "",
                "Slug": "",
                "DisplayInfo_Label": "",
                "DisplayInfo_PromotionBasedLabel": "",
                "NewPrice": "0",
                "PriceOriginal": "0",
                "PriceOriginal_Highest": "0",
                "PriceOriginal_Lowest": "0",
                "StartDate": "1900-01-01",
                "EndDate": "1900-01-01",
                "ImageURL": "",
                "ImageLabel": "",
                "Position": 0,
                "IsProduct": False,
                "IsFreeDeliveryOffer": False,
                "IsSingleProductPromotion": False,
                "BadgeQuantity": 0,
                "Logos": {
                    "PLPInUpperLeft": {
                        "List": [],
                        "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0},
                    },
                    "PLPAboveTitle": {
                        "List": [],
                        "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0},
                    },
                    "PLPBehindSizeUnit": {
                        "List": [],
                        "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0},
                    },
                },
                "IsProductOverMajorityAge": False,
                "Categories": {"List": [], "EmptyListItem": {"Name": ""}},
                "PromotionVariant": "",
                "PromotionPackage": "",
                "PromotionExplanation": "",
                "ProductSKU": "",
                "ProductLineItemId": "",
                "StampURL": "",
                "MaxOrderLimit": 0,
            },
        },
        "IsUnderAge": False,
        "ClickDelayValue": 0,
        "ProductCategories": "",
        "PromotionCategories": "",
        "Priority": 0,
        "UpdatedAt": "1900-01-01T00:00:00",
        "ProductCategoriesList": {"List": [], "EmptyListItem": ""},
        "PromotionCategoriesList": {"List": [], "EmptyListItem": ""},
        "PlacementId": "",
    },
    "Category": {
        "CategoryId": "",
        "CategoryLabel": "",
        "CategorySortOrder": "0",
        "Offers": {
            "List": [],
            "EmptyListItem": {
                "PromotionID": "",
                "Offer_Id": "",
                "PromotionSortOrder": "0",
                "Brand": "",
                "Name": "",
                "Example": "",
                "Variant": "",
                "Explanation": "",
                "Package": "",
                "Slug": "",
                "ImageURL": "",
                "ImageLabel": "",
                "MetaTitle": "",
                "MetaDescription": "",
                "NewPrice": "0",
                "PriceOriginal_Product": "0",
                "PriceOriginal_Highest": "0",
                "PriceOriginal_Lowest": "0",
                "IsOfflineSaleOnly": False,
                "IsProductOverMajorityAge": False,
                "DisplayInfo_Label": "",
                "DisplayInfo_PromotionBasedLabel": "",
                "StartDate": "1900-01-01",
                "EndDate": "1900-01-01",
                "IsFreeDeliveryOffer": False,
                "IsSingleProduct": False,
                "Product_SKU": "",
                "Product_LineItemId": "",
                "Product_Quantity": 0,
                "ProductLoyaltyInfoID": 0,
                "Product_IsNIX18": False,
                "Product_MaxOrderLimit": 0,
                "StampURL": "",
                "StoreNumberList": {"List": [], "EmptyListItem": ""},
            },
        },
        "SKUsAvailable": {"List": [], "EmptyListItem": ""},
        "NumberOfProducts": 0,
    },
}

_ORDER_LIST_URL = (
    "https://www.plus.nl/screenservices/ECP_Customer_CW/Account"
    "/OrdersContent/DataActionGetCustomerDetails"
)
_ORDER_DETAIL_URL = (
    "https://www.plus.nl/screenservices/ECP_Customer_CW/CustomerDetails"
    "/OrderDetailsContent/DataActionGetOrderDetails"
)
_ORDER_LIST_PAGE_URL = "https://www.plus.nl/bestellingen"

_ORDER_EMPTY_ITEM = {
    "Order_Id": "",
    "Order_Number": "",
    "WorkflowOrderState_Id": "",
    "DeliveryType_Id": 0,
    "DeliveryType_ServiceStatusLabel": "",
    "Order_DeliveryDate": "1900-01-01",
    "Order_DeliveryStartTime": "",
    "Order_DeliveryEndTime": "",
    "Order_CutOffMoment": "1900-01-01T00:00:00",
    "Order_FictionalCutOffMoment": "1900-01-01T00:00:00",
    "Order_TotalPrice": "0",
    "Order_InProgress": False,
    "CustomerName": "",
    "BusinessInterfaceId": "",
}

_SEARCH_URL = (
    "https://www.plus.nl/screenservices/ECP_Composition_CW/ProductLists"
    "/PLP_Content/DataActionGetProductListAndCategoryInfo"
)
_SEARCH_PAGE_URL = "https://www.plus.nl/zoekresultaten?SearchTerm="

# OutSystems EmptyListItem schema for search product list.
# Modelled on _PURCHASE_HISTORY_EMPTY_ITEM — adjust if payload discovery reveals differences.
_SEARCH_EMPTY_ITEM = {
    "SKU": "",
    "Brand": "",
    "Name": "",
    "Product_Subtitle": "",
    "Slug": "",
    "ImageURL": "",
    "ImageLabel": "",
    "MetaTitle": "",
    "MetaDescription": "",
    "OriginalPrice": "0",
    "NewPrice": "0",
    "Quantity": 0,
    "LineItemId": "",
    "IsProductOverMajorityAge": False,
    "Logos": {
        "PLPInUpperLeft": {
            "List": [],
            "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0},
        },
        "PLPAboveTitle": {
            "List": [],
            "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0},
        },
        "PLPBehindSizeUnit": {
            "List": [],
            "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0},
        },
    },
    "EAN": "",
    "Packging": "",
    "Categories": {"List": [], "EmptyListItem": {"Name": ""}},
    "IsAvailable": False,
    "PromotionLabel": "",
    "PromotionBasedLabel": "",
    "PromotionStartDate": "1900-01-01",
    "PromotionEndDate": "1900-01-01",
    "IsFreeDeliveryOffer": False,
    "IsOfflineSaleOnly": False,
    "MaxOrderLimit": 0,
    "CitrusAdId": "",
    "IsLocalItem": False,
}

_PURCHASE_HISTORY_URL = (
    "https://www.plus.nl/screenservices/ECP_Customer_CW/Account"
    "/RecentlyBoughtProducts/DataActionGetProducts"
)
_PURCHASE_HISTORY_PAGE_URL = "https://www.plus.nl/eerder-gekochte-producten"

# OutSystems type schema for the ProductList.EmptyListItem — must be sent verbatim.
_PURCHASE_HISTORY_EMPTY_ITEM = {
    "SKU": "",
    "Brand": "",
    "Name": "",
    "Product_Subtitle": "",
    "Slug": "",
    "ImageURL": "",
    "ImageLabel": "",
    "MetaTitle": "",
    "MetaDescription": "",
    "OriginalPrice": "0",
    "NewPrice": "0",
    "Quantity": 0,
    "LineItemId": "",
    "IsProductOverMajorityAge": False,
    "Logos": {
        "PLPInUpperLeft": {
            "List": [],
            "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0},
        },
        "PLPAboveTitle": {
            "List": [],
            "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0},
        },
        "PLPBehindSizeUnit": {
            "List": [],
            "EmptyListItem": {"Name": "", "LongDescription": "", "URL": "", "Order": 0},
        },
    },
    "EAN": "",
    "Packging": "",
    "Categories": {"List": [], "EmptyListItem": {"Name": ""}},
    "IsAvailable": False,
    "PromotionLabel": "",
    "PromotionBasedLabel": "",
    "PromotionStartDate": "1900-01-01",
    "PromotionEndDate": "1900-01-01",
    "IsFreeDeliveryOffer": False,
    "IsOfflineSaleOnly": False,
    "MaxOrderLimit": 0,
    "CitrusAdId": "",
    "IsLocalItem": False,
}

# OAuth2 login URL extracted from the original R code (plus_remote_functions.R:33).
# client_id=web_ecop_eprod is the PLUS.nl web app identifier.
_LOGIN_URL = (
    "https://aanmelden.plus.nl/plus/login/"
    "?goto=https%3A%2F%2Faanmelden.plus.nl%2Fplus%2Fauth%2Foauth2.0%2Fv1%2Fauthorize"
    "%3Fresponse_type%3Dcode%26scope%3Dopenid%2Bprofile%26client_id%3Dweb_ecop_eprod"
    "%26redirect_uri%3Dhttps%253A%252F%252Fwww.plus.nl%252FCallback"
)
_CART_URL = "https://www.plus.nl/winkelwagen"


class PlusClient:
    """
    Async context manager for PLUS.nl.

    Usage::

        async with PlusClient(headless=False) as client:
            await client.login(email, password)
            await client.add_to_cart("957806", quantity=2)
            cart = await client.get_cart()
            print(cart)
            client.print_api_discoveries()
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        # Discovered API calls logged during the session
        self._api_calls: list[dict] = []
        self._bearer_token: Optional[str] = None

        # Session state captured from intercepted request/response bodies
        self._session = SessionState()

        # Cart primed by _parse_cart_response; consumed once by get_cart_api()
        self._primed_cart: Optional["Cart"] = None
        # Task handle for the DataActionGetCartById parse — awaited in get_session_state()
        self._cart_parse_task: Optional[asyncio.Task] = None
        # Ground-truth search request body captured from the real browser PLP call.
        # Used to verify/repair _build_search_payload against a live session — a
        # mismatched screenData payload silently returns all items as unavailable.
        self._real_search_payload: Optional[dict] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "PlusClient":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="nl-NL",
            timezone_id="Europe/Amsterdam",
        )
        self._page = await self._context.new_page()
        self._page.on("request", self._on_request)
        self._page.on("response", self._on_response)
        return self

    async def __aexit__(self, *_) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ------------------------------------------------------------------
    # Network interception — discovers direct API endpoints for future use
    # ------------------------------------------------------------------

    def _on_request(self, request) -> None:
        url = request.url
        if not self._is_api_call(url):
            return
        entry = {"method": request.method, "url": url}

        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer ") and not self._bearer_token:
            self._bearer_token = auth[7:]
            entry["bearer_captured"] = True

        # Harvest version info and session fields from OutSystems screenservices bodies.
        # Each OS module has its own moduleVersion/apiVersion — capture per-module.
        if "screenservices" in url and request.method == "POST":
            try:
                body = request.post_data_json
                if isinstance(body, dict):
                    vi = body.get("versionInfo", {})
                    mv = vi.get("moduleVersion", "")
                    av = vi.get("apiVersion", "")
                    if mv:
                        # Always keep a generic fallback
                        if not self._session.module_version:
                            self._session.module_version = mv
                            self._session.api_version = av
                        # Capture module-specific versions
                        if "ECP_Cart_CW" in url and not self._session.cart_module_version:
                            self._session.cart_module_version = mv
                            self._session.cart_api_version = av
                        # Each ECP_Cart_CW action has its own apiVersion hash.
                        # When newly discovered, persist to disk so future sessions skip priming.
                        if (
                            "ActionCheckoutItem_Add" in url
                            and not self._session.cart_add_api_version
                        ):
                            self._session.cart_add_api_version = av
                            version_cache.save_from_session(self._session)
                        if (
                            "DataActionGetCartById" in url
                            and not self._session.cart_get_api_version
                        ):
                            self._session.cart_get_api_version = av
                        if (
                            "ActionCheckoutItem_Remove" in url
                            and not self._session.cart_remove_api_version
                        ):
                            self._session.cart_remove_api_version = av
                            version_cache.save_from_session(self._session)
                        if (
                            "DataActionGetPromotionList_Optimization" in url
                            and not self._session.promotions_api_version
                        ):
                            self._session.promotions_api_version = av
                            version_cache.save_from_session(self._session)
                        if (
                            "DataActionPromotionOfferDetail_Get" in url
                            and not self._session.promo_detail_api_version
                        ):
                            self._session.promo_detail_api_version = av
                            version_cache.save_from_session(self._session)
                        if (
                            "OrdersContent/DataActionGetCustomerDetails" in url
                            and not self._session.order_list_api_version
                        ):
                            self._session.order_list_api_version = av
                            version_cache.save_from_session(self._session)
                        if (
                            "OrderDetailsContent/DataActionGetOrderDetails" in url
                            and not self._session.order_detail_api_version
                        ):
                            self._session.order_detail_api_version = av
                            version_cache.save_from_session(self._session)
                        if (
                            "RecentlyBoughtProducts/DataActionGetProducts" in url
                            and not self._session.purchase_history_api_version
                        ):
                            self._session.purchase_history_api_version = av
                            version_cache.save_from_session(self._session)
                        if (
                            "DataActionGetProductListAndCategoryInfo" in url
                            and not self._session.search_api_version
                        ):
                            self._session.search_api_version = av
                            version_cache.save_from_session(self._session)
                    # Capture the real browser PLP request body once — the ground
                    # truth for verifying our hand-built search payload.
                    if (
                        "DataActionGetProductListAndCategoryInfo" in url
                        and self._real_search_payload is None
                    ):
                        self._real_search_payload = body
                        log.debug(
                            "[diag] captured real browser search payload — "
                            "compare with _build_search_payload to fix availability"
                        )
                    params = body.get("inputParameters", {})
                    if params.get("CheckoutId") and not self._session.checkout_id:
                        self._session.checkout_id = params["CheckoutId"]
                        self._session.checkout_version = params.get("CheckoutVersion", 0)
                    if params.get("OneWelcomeUserId") and not self._session.onewelcome_user_id:
                        self._session.onewelcome_user_id = params["OneWelcomeUserId"]
                    # Harvest LineItemId↔SKU mappings from add/remove request bodies
                    if params.get("SKU") and params.get("LineItemId"):
                        self._session.line_item_ids[params["SKU"]] = params["LineItemId"]
            except Exception:
                pass

        self._api_calls.append(entry)

    def _on_response(self, response) -> None:
        url = response.url
        if not self._is_api_call(url):
            return
        for entry in reversed(self._api_calls):
            if entry["url"] == url and "status" not in entry:
                entry["status"] = response.status
                break
        # Parse any cart-mutating response to keep line_item_ids in sync.
        # Fires for both page-load calls (DataActionGetCartById) and browser-based
        # button clicks (Add/Remove), covering the prime methods automatically.
        if response.status == 200 and any(
            k in url
            for k in (
                "DataActionGetCartById",
                "ActionCheckoutItem_Add",
                "ActionCheckoutItem_Remove",
            )
        ):
            task = asyncio.ensure_future(self._parse_cart_response(response))
            if "DataActionGetCartById" in url:
                self._cart_parse_task = task
        if (
            response.status == 200
            and "ActionStoreWrapper_GetGeneralDetails" in url
            and not self._session.store_number
        ):
            asyncio.ensure_future(self._parse_store_response(response))
        if (
            response.status == 200
            and "ActionCustomerTemp_GetDetails" in url
            and not self._session.user_store_id
        ):
            asyncio.ensure_future(self._parse_customer_response(response))

    async def _parse_cart_response(self, response) -> None:
        try:
            body = await response.json()
            data = body.get("data", {})
            checkout = data.get("Checkout") or data.get("Cart") or next(iter(data.values()), {})
            if isinstance(checkout, dict):
                if "Version" in checkout:
                    self._session.checkout_version = checkout["Version"]
                self._update_line_item_ids(checkout)
                self._primed_cart = _parse_cart_from_checkout(checkout)
        except Exception:
            pass

    async def _parse_store_response(self, response) -> None:
        try:
            body = await response.json()
            store = body.get("data", {}).get("Store", {})
            if store.get("Store_Number"):
                self._session.store_number = int(store["Store_Number"])
                if store.get("Store_Name"):
                    self._session.store_name = str(store["Store_Name"])
        except Exception:
            pass

    async def _parse_customer_response(self, response) -> None:
        try:
            body = await response.json()
            details = body.get("data", {}).get("CustomerTempDetailsR", {})
            if details.get("PreferredStoreId"):
                self._session.user_store_id = str(details["PreferredStoreId"])
        except Exception:
            pass

    @staticmethod
    def _is_api_call(url: str) -> bool:
        # Exclude login/auth server and static assets
        if "aanmelden.plus.nl" in url:
            return False
        ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
        if ext in ("js", "css", "png", "jpg", "jpeg", "webp", "svg", "ico", "woff", "woff2", "ttf"):
            return False
        # Capture all XHR/fetch calls to plus.nl — OutSystems apps use non-standard paths
        return "plus.nl" in url and any(
            kw in url
            for kw in [
                "/api/",
                "/rest/",
                "/service",
                "/screenservice",
                "/action/",
                "cart",
                "basket",
                "order",
                "product",
                "search",
                "screenservices",
            ]
        )

    async def add_to_cart_api(self, sku: str, quantity: int = 1) -> dict:
        """
        Add to cart via a direct fetch() call executed inside the page.

        Running the fetch from inside the browser page means it carries the
        correct Origin, Referer, and Sec-Fetch-* headers automatically — the
        same as a real XHR from plus.nl's own JavaScript. No page navigation,
        no button clicks; just one HTTP round-trip (~200ms).

        Requires the page to currently be on a plus.nl domain (same-origin).
        """
        import time

        payload = {
            "versionInfo": self._session.version_info_for_add(),
            "viewName": "MainFlow.SearchPage",
            "inputParameters": {
                "IsOrderEditMode": False,
                "CheckoutId": self._session.checkout_id,
                "CheckoutVersion": self._session.checkout_version,
                "OrderEditId": "",
                "SKU": sku,
                "QuantityToAdd": quantity,
                "ChannelId": "1690b994-7511-41cc-a1bc-aacf2726f218",
                "OneWelcomeUserId": self._session.onewelcome_user_id,
            },
        }

        t0 = time.perf_counter()
        result = await self._page.evaluate(
            """async (payload) => {
                // OutSystems CSRF: extract the 'crf=' field from the nr2Users cookie
                // and send it as the x-csrftoken header — exactly what OS's own JS does.
                const cookieMap = {};
                document.cookie.split('; ').forEach(c => {
                    const eq = c.indexOf('=');
                    if (eq > 0) cookieMap[c.slice(0, eq)] = c.slice(eq + 1);
                });
                const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
                const crfField = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
                const csrfToken = crfField.slice(crfField.indexOf('=') + 1);

                const resp = await fetch(
                    'https://www.plus.nl/screenservices/ECP_Cart_CW/ActionCheckoutItem_Add',
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'x-csrftoken': csrfToken,
                            'outsystems-locale': 'nl-NL'
                        },
                        body: JSON.stringify(payload),
                        credentials: 'include'
                    }
                );
                if (!resp.ok) {
                    const body = await resp.text().catch(() => '');
                    throw new Error('HTTP ' + resp.status + ' — ' + body.slice(0, 300));
                }
                return await resp.json();
            }""",
            payload,
        )
        elapsed = time.perf_counter() - t0
        log.debug("[API] ActionCheckoutItem_Add → 200 in %.0fms", elapsed * 1000)

        data = result.get("data", {})
        if "Checkout" not in data:
            import json as _json_mod

            vi = result.get("versionInfo", {})
            if vi.get("hasApiVersionChanged"):
                # PLUS.nl deployed — wipe cached versions so next session re-discovers
                self._session.cart_add_api_version = ""
                self._session.cart_remove_api_version = ""
                version_cache.save_from_session(self._session)
                raise RuntimeError(
                    "PLUS.nl heeft een nieuwe versie uitgerold (hasApiVersionChanged). "
                    "Cache gewist — herstart de sessie om opnieuw te primen."
                )
            print(f"[API] Unexpected response: {_json_mod.dumps(result)[:500]}")
            raise RuntimeError("Geen 'Checkout' in response — zie debug output hierboven")

        checkout = data["Checkout"]
        self._session.checkout_version = checkout["Version"]
        self._update_line_item_ids(checkout)
        return checkout

    async def get_cart_api(self) -> "Cart":
        """
        Fetch current cart state via a direct API call — no page navigation.

        Requires checkout_id (populated by get_session_state). Uses
        DataActionGetCartById which is the same call the cart page fires on load.

        If the browser already fired DataActionGetCartById during session setup
        (intercepted by _parse_cart_response), returns that primed cart instead
        of making a redundant second call — this avoids failures when the cached
        apiVersion is stale and the browser hasn't yet primed a fresh one.
        """
        import logging as _logging

        _log = _logging.getLogger(__name__)

        if self._primed_cart is not None:
            _log.info("get_cart_api — primed cart beschikbaar, geen fetch nodig")
            cart = self._primed_cart
            self._primed_cart = None
            return cart

        _log.info(
            "get_cart_api — geen primed cart; fetch starten (cart_get_api_version=%s)",
            bool(self._session.cart_get_api_version),
        )
        import time as _time

        if not self._session.cart_get_api_version:
            # Navigate to cart once so the page fires DataActionGetCartById
            # and we intercept the apiVersion.
            await self._page.goto(_CART_URL)
            await self._page.wait_for_load_state("networkidle", timeout=15_000)
            await asyncio.sleep(0)

        payload = {
            "versionInfo": self._session.version_info_for_get_cart(),
            "viewName": "MainFlow.Cart",
            "inputParameters": {
                "CheckoutId": self._session.checkout_id,
            },
        }

        t0 = _time.perf_counter()
        result = await self._page.evaluate(
            """async (payload) => {
                const cookieMap = {};
                document.cookie.split('; ').forEach(c => {
                    const eq = c.indexOf('=');
                    if (eq > 0) cookieMap[c.slice(0, eq)] = c.slice(eq + 1);
                });
                const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
                const crf = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
                const csrfToken = crf.slice(crf.indexOf('=') + 1);
                const resp = await fetch(
                    'https://www.plus.nl/screenservices/ECP_Cart_CW/DataActionGetCartById',
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'x-csrftoken': csrfToken,
                            'outsystems-locale': 'nl-NL',
                        },
                        body: JSON.stringify(payload),
                        credentials: 'include',
                    }
                );
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return await resp.json();
            }""",
            payload,
        )
        elapsed = _time.perf_counter() - t0
        _log.info("get_cart_api — page.evaluate klaar in %.0f ms", elapsed * 1000)
        log.debug("[API] DataActionGetCartById → 200 in %.0fms", elapsed * 1000)

        vi = result.get("versionInfo", {})
        if vi.get("hasApiVersionChanged"):
            self._session.cart_get_api_version = ""
            version_cache.save_from_session(self._session)
            raise RuntimeError("hasApiVersionChanged — cache gewist, herstart sessie")

        data = result.get("data", {})
        checkout = data.get("Checkout") or data.get("Cart") or next(iter(data.values()), {})
        if checkout and isinstance(checkout, dict):
            if "Version" in checkout:
                self._session.checkout_version = checkout["Version"]
            self._update_line_item_ids(checkout)
        return _parse_cart_from_checkout(checkout or {})

    # ------------------------------------------------------------------
    # Remove from cart — direct API
    # ------------------------------------------------------------------

    def _update_line_item_ids(self, checkout: dict) -> None:
        """Refresh SKU→LineItemId map from any checkout response."""
        for item in checkout.get("LineItemList", {}).get("List", []):
            sku = item.get("SKU", "")
            lid = item.get("LineItemId", "")
            if sku and lid:
                self._session.line_item_ids[sku] = lid

    # ------------------------------------------------------------------
    # Promotions — direct API
    # ------------------------------------------------------------------

    async def get_promotions_api(self, next_week: bool = False) -> "PromotionResult":
        """
        Fetch current (or next week's) PLUS promotions via a direct API call.

        Uses page.evaluate(fetch(...)) so it inherits all browser cookies and
        security headers automatically. Requires store_number, user_store_id, and
        promotions_api_version — all populated automatically during login/cart
        navigation; the first call navigates to /aanbiedingen to prime them.

        Returns a PromotionResult with one Promotion per offer across all categories,
        excluding free-delivery deals.
        """
        import time as _time

        if not self._session.promotions_api_version:
            # Navigate to promotions page once to intercept versionInfo + store data
            print("[*] promotions apiVersion onbekend — navigeer naar /aanbiedingen…")
            await self._page.goto("https://www.plus.nl/aanbiedingen")
            await self._page.wait_for_load_state("networkidle", timeout=25_000)
            await asyncio.sleep(0)  # let ensure_future tasks complete

        payload = self._build_promotions_payload(next_week=next_week)

        t0 = _time.perf_counter()
        result = await self._page.evaluate(
            """async (payload) => {
                const cookieMap = {};
                document.cookie.split('; ').forEach(c => {
                    const eq = c.indexOf('=');
                    if (eq > 0) cookieMap[c.slice(0, eq)] = c.slice(eq + 1);
                });
                const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
                const crfField = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
                const csrfToken = crfField.slice(crfField.indexOf('=') + 1);

                const resp = await fetch(
                    'https://www.plus.nl/screenservices/ECP_Composition_CW/Promotions' +
                    '/Promotion_LP_Content_TF_Optimization/DataActionGetPromotionList_Optimization',
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'x-csrftoken': csrfToken,
                            'outsystems-locale': 'nl-NL'
                        },
                        body: JSON.stringify(payload),
                        credentials: 'include'
                    }
                );
                if (!resp.ok) {
                    const body = await resp.text().catch(() => '');
                    throw new Error('HTTP ' + resp.status + ' — ' + body.slice(0, 300));
                }
                return await resp.json();
            }""",
            payload,
        )
        elapsed = _time.perf_counter() - t0
        label = "volgende week" if next_week else "huidige week"
        log.debug(
            "[API] DataActionGetPromotionList_Optimization (%s) → 200 in %.0fms",
            label,
            elapsed * 1000,
        )

        vi = result.get("versionInfo", {})
        if vi.get("hasApiVersionChanged"):
            self._session.promotions_api_version = ""
            version_cache.save_from_session(self._session)
            raise RuntimeError(
                "PLUS.nl heeft een nieuwe versie uitgerold (hasApiVersionChanged). "
                "Cache gewist — herstart de sessie om opnieuw te primen."
            )

        return _parse_promotion_result(result["data"])

    async def get_promotion_products_api(self, slug: str) -> list["PromotionProduct"]:
        """
        Fetch individual products for a group promotion by its slug (e.g. '4431-96').

        Only meaningful for promotions where is_single_product is False.
        Returns an empty list for free-delivery offers (no products to show).
        ~400ms per call.
        """
        import time as _time

        if not self._session.promo_detail_api_version:
            # Navigate to any promo detail page once to prime the apiVersion
            print(f"[*] promo_detail apiVersion onbekend — navigeer naar /aanbiedingen/{slug}…")
            await self._page.goto(f"https://www.plus.nl/aanbiedingen/{slug}")
            await self._page.wait_for_load_state("networkidle", timeout=25_000)
            await asyncio.sleep(0)

        payload = {
            "versionInfo": self._session.version_info_for_promo_detail(),
            "viewName": "MainFlow.Promotions",
            "screenData": {
                "variables": {
                    "CheckoutId": self._session.checkout_id,
                    "IsOrderEditMode": False,
                    "OrderEditId": "",
                    "StoreChannelD": _CHANNEL_ID,
                    "LineItemRecList": {
                        "List": [
                            {"LineItemId": lid, "SKU": sku, "Quantity": 0}
                            for sku, lid in self._session.line_item_ids.items()
                        ]
                    },
                    "StoreNumber": self._session.store_number,
                    "PromotionOfferId": slug,
                    "_promotionOfferIdInDataFetchStatus": 1,
                    "OneWelcomeUserId": self._session.onewelcome_user_id,
                    "_oneWelcomeUserIdInDataFetchStatus": 1,
                    "IsDesktop": True,
                    "_isDesktopInDataFetchStatus": 1,
                    "IsTablet": False,
                    "_isTabletInDataFetchStatus": 1,
                    "IsPhone": False,
                    "_isPhoneInDataFetchStatus": 1,
                    "IsCustomerUnderAge": False,
                    "_isCustomerUnderAgeInDataFetchStatus": 1,
                    "IsTimetraveler": False,
                    "_isTimetravelerInDataFetchStatus": 1,
                }
            },
        }

        t0 = _time.perf_counter()
        result = await self._page.evaluate(
            """async (payload) => {
                const cookieMap = {};
                document.cookie.split('; ').forEach(c => {
                    const eq = c.indexOf('=');
                    if (eq > 0) cookieMap[c.slice(0, eq)] = c.slice(eq + 1);
                });
                const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
                const crfField = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
                const csrfToken = crfField.slice(crfField.indexOf('=') + 1);

                const resp = await fetch(
                    'https://www.plus.nl/screenservices/ECP_Promotion_CW/PromotionDetailsFlow' +
                    '/PromotionOffer_DP_Content/DataActionPromotionOfferDetail_Get',
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'x-csrftoken': csrfToken,
                            'outsystems-locale': 'nl-NL'
                        },
                        body: JSON.stringify(payload),
                        credentials: 'include'
                    }
                );
                if (!resp.ok) {
                    const body = await resp.text().catch(() => '');
                    throw new Error('HTTP ' + resp.status + ' — ' + body.slice(0, 300));
                }
                return await resp.json();
            }""",
            payload,
        )
        elapsed = _time.perf_counter() - t0
        log.debug(
            "[API] DataActionPromotionOfferDetail_Get (%s) → 200 in %.0fms", slug, elapsed * 1000
        )

        vi = result.get("versionInfo", {})
        if vi.get("hasApiVersionChanged"):
            self._session.promo_detail_api_version = ""
            version_cache.save_from_session(self._session)
            raise RuntimeError(
                "PLUS.nl heeft een nieuwe versie uitgerold (hasApiVersionChanged). "
                "Cache gewist — herstart de sessie om opnieuw te primen."
            )

        return _parse_promotion_products(result["data"])

    async def get_order_list_api(self, offset: int = 0) -> list["OrderSummary"]:
        """
        Fetch the list of all past and current orders.

        Returns OrderSummary objects with Order_Id, delivery date, total, status.
        The server returns all orders in one call (no pagination observed yet).
        Navigate to /bestellingen once to prime the apiVersion if not cached.
        """
        import time as _time

        if not self._session.order_list_api_version:
            print("[*] order_list apiVersion onbekend — navigeer naar /bestellingen…")
            await self._page.goto(_ORDER_LIST_PAGE_URL)
            await self._page.wait_for_load_state("networkidle", timeout=30_000)
            await asyncio.sleep(3)

        payload = {
            "versionInfo": self._session.version_info_for_order_list(),
            "viewName": "AccountFlow.OrdersOverview",
            "screenData": {
                "variables": {
                    "QueryOffset": offset,
                    "Orders_Active": {"List": [], "EmptyListItem": _ORDER_EMPTY_ITEM},
                    "Orders_Previous": {"List": [], "EmptyListItem": _ORDER_EMPTY_ITEM},
                    "IsLoadingMore": True,
                    "IsShowData": False,
                    "HasMoreItemsToLoad": False,
                    "OneWelcomeUserId": self._session.onewelcome_user_id,
                    "_oneWelcomeUserIdInDataFetchStatus": 1,
                    "IsDesktop": True,
                    "_isDesktopInDataFetchStatus": 1,
                    "IsTablet": False,
                    "_isTabletInDataFetchStatus": 1,
                    "IsToOverview": False,
                    "_isToOverviewInDataFetchStatus": 1,
                    "IsToShowSideMenu": True,
                    "_isToShowSideMenuInDataFetchStatus": 1,
                    "CurrDateTime": __import__("datetime")
                    .datetime.utcnow()
                    .strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "_currDateTimeInDataFetchStatus": 1,
                }
            },
        }

        t0 = _time.perf_counter()
        result = await self._page.evaluate(
            """async (payload) => {
                const cookieMap = {};
                document.cookie.split('; ').forEach(c => {
                    const eq = c.indexOf('=');
                    if (eq > 0) cookieMap[c.slice(0, eq)] = c.slice(eq + 1);
                });
                const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
                const crf = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
                const csrfToken = crf.slice(crf.indexOf('=') + 1);
                const resp = await fetch(
                    'https://www.plus.nl/screenservices/ECP_Customer_CW/Account' +
                    '/OrdersContent/DataActionGetCustomerDetails',
                    { method: 'POST',
                      headers: { 'Content-Type': 'application/json',
                                 'x-csrftoken': csrfToken, 'outsystems-locale': 'nl-NL' },
                      body: JSON.stringify(payload), credentials: 'include' }
                );
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return await resp.json();
            }""",
            payload,
        )
        elapsed = _time.perf_counter() - t0
        print(f"[API] DataActionGetCustomerDetails → 200 in {elapsed * 1000:.0f}ms")

        vi = result.get("versionInfo", {})
        if vi.get("hasApiVersionChanged"):
            self._session.order_list_api_version = ""
            version_cache.save_from_session(self._session)
            raise RuntimeError("hasApiVersionChanged — cache gewist, herstart sessie")

        data = result["data"]
        orders: list[OrderSummary] = []
        for is_active, key in [(True, "Orders_Struct_Active"), (False, "Orders_Struct_Previous")]:
            for o in data.get(key, {}).get("List", []):
                orders.append(
                    OrderSummary(
                        order_id=o.get("Order_Id", ""),
                        order_number=o.get("Order_Number", ""),
                        delivery_date=o.get("Order_DeliveryDate", ""),
                        delivery_start=o.get("Order_DeliveryStartTime", ""),
                        delivery_end=o.get("Order_DeliveryEndTime", ""),
                        total_price=_safe_float(o.get("Order_TotalPrice", "0")),
                        status=o.get("DeliveryType_ServiceStatusLabel", ""),
                        channel=o.get("BusinessInterfaceId", ""),
                        is_active=is_active,
                    )
                )
        return orders

    async def get_order_detail_api(self, order_id: str) -> "OrderDetail":
        """
        Fetch full line items for a single order by its Order_Id UUID.

        Returns an OrderDetail with items from both AvailableItemList and
        UnavailableItemList (marked available=False). Navigate to /order-details
        once to prime the apiVersion if not cached.
        """
        import time as _time

        if not self._session.order_detail_api_version:
            print("[*] order_detail apiVersion onbekend — navigeer naar /order-details…")
            await self._page.goto(f"https://www.plus.nl/order-details?OrderId={order_id}")
            await self._page.wait_for_load_state("networkidle", timeout=30_000)
            await asyncio.sleep(3)

        payload = {
            "versionInfo": self._session.version_info_for_order_detail(),
            "viewName": "AccountFlow.OrderDetail",
            "screenData": {
                "variables": {
                    "ShowChangeOrderPopUp": False,
                    "ShowCancelOrderPopup": False,
                    "VoucherJSON": "",
                    "CurrentCartId": "",
                    "Locale": "nl-NL",
                    "IsPhone": False,
                    "_isPhoneInDataFetchStatus": 1,
                    "IsTablet": False,
                    "_isTabletInDataFetchStatus": 1,
                    "IsDesktop": True,
                    "_isDesktopInDataFetchStatus": 1,
                    "IsToShowSideMenu": True,
                    "_isToShowSideMenuInDataFetchStatus": 1,
                    "OneWelcomeUserId": self._session.onewelcome_user_id,
                    "_oneWelcomeUserIdInDataFetchStatus": 1,
                    "OrderId": order_id,
                    "_orderIdInDataFetchStatus": 1,
                    "CurrDateTime": __import__("datetime")
                    .datetime.utcnow()
                    .strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "_currDateTimeInDataFetchStatus": 1,
                    "ExternalChannelId": _CHANNEL_ID,
                    "_externalChannelIdInDataFetchStatus": 1,
                    "IsOrderEditMode": False,
                    "_isOrderEditModeInDataFetchStatus": 1,
                    "IsPunchOutSession": False,
                    "_isPunchOutSessionInDataFetchStatus": 1,
                }
            },
        }

        t0 = _time.perf_counter()
        result = await self._page.evaluate(
            """async (payload) => {
                const cookieMap = {};
                document.cookie.split('; ').forEach(c => {
                    const eq = c.indexOf('=');
                    if (eq > 0) cookieMap[c.slice(0, eq)] = c.slice(eq + 1);
                });
                const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
                const crf = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
                const csrfToken = crf.slice(crf.indexOf('=') + 1);
                const resp = await fetch(
                    'https://www.plus.nl/screenservices/ECP_Customer_CW/CustomerDetails' +
                    '/OrderDetailsContent/DataActionGetOrderDetails',
                    { method: 'POST',
                      headers: { 'Content-Type': 'application/json',
                                 'x-csrftoken': csrfToken, 'outsystems-locale': 'nl-NL' },
                      body: JSON.stringify(payload), credentials: 'include' }
                );
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return await resp.json();
            }""",
            payload,
        )
        elapsed = _time.perf_counter() - t0
        print(f"[API] DataActionGetOrderDetails ({order_id[:8]}…) → 200 in {elapsed * 1000:.0f}ms")

        vi = result.get("versionInfo", {})
        if vi.get("hasApiVersionChanged"):
            self._session.order_detail_api_version = ""
            version_cache.save_from_session(self._session)
            raise RuntimeError("hasApiVersionChanged — cache gewist, herstart sessie")

        d = result["data"]["OrderHistoryDetail"]
        items: list[OrderLineItem] = []
        for available, key in [(True, "AvailableItemList"), (False, "UnavailableItemList")]:
            for it in d.get(key, {}).get("List", []):
                items.append(
                    OrderLineItem(
                        sku=it.get("SKU", ""),
                        name=it.get("Name", ""),
                        subtitle=it.get("Subtitle", ""),
                        slug=it.get("Slug", ""),
                        quantity=it.get("Quantity", 0),
                        price=_safe_float(it.get("Price", "0")),
                        category=it.get("Category", ""),
                        image_url=it.get("ImageURL", ""),
                        available=available,
                    )
                )
        return OrderDetail(
            order_id=d.get("Order_Id", ""),
            order_number=d.get("Order_Number", ""),
            delivery_date=d.get("Order_DeliveryDate", ""),
            store_name=d.get("Order_StoreName", ""),
            status=d.get("DeliveryType_ServiceStatusLabel", ""),
            address=d.get("Order_ShippingAddress", ""),
            items=items,
        )

    async def get_purchase_history_api(
        self,
        all_pages: bool = True,
        page_size: int = 36,
    ) -> list["PurchasedProduct"]:
        """
        Fetch all previously bought products from PLUS.nl — online AND in-store.

        Returns a deduplicated product catalogue (~70 items across 2 pages) with
        current prices and stock. No purchase dates are available at this level;
        use get_order_list_api() + get_order_detail_api() for dated online orders.

        The Period parameter is sent (current promo week) but the server ignores it
        and returns the full all-time purchase history, paginated at 36 per page.
        """
        import time as _time

        if not self._session.purchase_history_api_version:
            print(
                "[*] purchase_history apiVersion onbekend — navigeer naar eerder-gekochte-producten…"
            )
            await self._page.goto(_PURCHASE_HISTORY_PAGE_URL)
            await self._page.wait_for_load_state("networkidle", timeout=25_000)
            await asyncio.sleep(1)

        products: list[PurchasedProduct] = []
        page = 1

        while True:
            payload = self._build_purchase_history_payload(page, page_size)
            t0 = _time.perf_counter()
            result = await self._page.evaluate(
                """async (payload) => {
                    const cookieMap = {};
                    document.cookie.split('; ').forEach(c => {
                        const eq = c.indexOf('=');
                        if (eq > 0) cookieMap[c.slice(0, eq)] = c.slice(eq + 1);
                    });
                    const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
                    const crfField = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
                    const csrfToken = crfField.slice(crfField.indexOf('=') + 1);

                    const resp = await fetch(
                        'https://www.plus.nl/screenservices/ECP_Customer_CW/Account' +
                        '/RecentlyBoughtProducts/DataActionGetProducts',
                        {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'x-csrftoken': csrfToken,
                                'outsystems-locale': 'nl-NL'
                            },
                            body: JSON.stringify(payload),
                            credentials: 'include'
                        }
                    );
                    if (!resp.ok) {
                        const body = await resp.text().catch(() => '');
                        throw new Error('HTTP ' + resp.status + ' — ' + body.slice(0, 300));
                    }
                    return await resp.json();
                }""",
                payload,
            )
            elapsed = _time.perf_counter() - t0
            print(f"[API] DataActionGetProducts (page {page}) → 200 in {elapsed * 1000:.0f}ms")

            vi = result.get("versionInfo", {})
            if vi.get("hasApiVersionChanged"):
                self._session.purchase_history_api_version = ""
                version_cache.save_from_session(self._session)
                raise RuntimeError(
                    "PLUS.nl heeft een nieuwe versie uitgerold (hasApiVersionChanged). "
                    "Cache gewist — herstart de sessie om opnieuw te primen."
                )

            page_products = _parse_purchased_products(result["data"])
            products.extend(page_products)

            if not all_pages or len(page_products) < page_size:
                break
            page += 1

        return products

    async def search_products_api(
        self, query: str, store_number: int | None = None
    ) -> list["Product"]:
        """
        Search PLUS.nl products via direct API call.

        Uses DataActionGetProductListAndCategoryInfo. The payload format is
        inferred from similar endpoints; run explore_search.py to capture and
        verify the exact format against a live session.

        Primes the apiVersion by navigating to the search results page on the
        first call if not already cached — same pattern as other endpoints.
        """
        import time as _time
        import urllib.parse as _up

        effective_store = store_number or self._session.store_number

        if not self._session.search_api_version:
            print("[*] search apiVersion onbekend — navigeer naar zoekresultaten…")
            safe_q = _up.quote(query or "melk")
            await self._page.goto(f"{_SEARCH_PAGE_URL}{safe_q}")
            await self._page.wait_for_load_state("networkidle", timeout=25_000)
            await asyncio.sleep(1)

        payload = self._build_search_payload(query, effective_store)

        t0 = _time.perf_counter()
        result = await self._page.evaluate(
            """async (payload) => {
                const cookieMap = {};
                document.cookie.split('; ').forEach(c => {
                    const eq = c.indexOf('=');
                    if (eq > 0) cookieMap[c.slice(0, eq)] = c.slice(eq + 1);
                });
                const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
                const crf = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
                const csrfToken = crf.slice(crf.indexOf('=') + 1);
                const resp = await fetch(
                    'https://www.plus.nl/screenservices/ECP_Composition_CW/ProductLists'
                    + '/PLP_Content/DataActionGetProductListAndCategoryInfo',
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'x-csrftoken': csrfToken,
                            'outsystems-locale': 'nl-NL',
                        },
                        body: JSON.stringify(payload),
                        credentials: 'include',
                    }
                );
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return await resp.json();
            }""",
            payload,
        )
        elapsed = _time.perf_counter() - t0
        log.debug(
            "[API] DataActionGetProductListAndCategoryInfo (%r) → 200 in %.0fms",
            query,
            elapsed * 1000,
        )

        vi = result.get("versionInfo", {})
        if vi.get("hasApiVersionChanged"):
            self._session.search_api_version = ""
            version_cache.save_from_session(self._session)
            raise RuntimeError("hasApiVersionChanged — cache gewist, herstart sessie")

        products = _parse_search_results(result.get("data", {}), effective_store)
        if not products:
            # Response might have different structure — log for diagnosis
            print(
                f"[API] Zoekresultaten leeg of onbekende structuur. "
                f"Voer explore_search.py uit om payload te verifiëren. "
                f"Keys in data: {list(result.get('data', {}).keys())[:10]}"
            )
        return products

    @staticmethod
    def _promo_week() -> dict:
        """Current PLUS promo week (Wed–Tue) as the API's Period struct."""
        import datetime as _dt

        today = _dt.date.today()
        # Most recent Wednesday on/before today (weekday: Mon=0 … Wed=2).
        start = today - _dt.timedelta(days=(today.weekday() - 2) % 7)
        return {
            "FromDate": start.isoformat(),
            "ToDate": (start + _dt.timedelta(days=6)).isoformat(),
        }

    def _build_search_payload(
        self, query: str, store_number: int, page: int = 1, page_size: int = 24
    ) -> dict:
        """Build the PLP search payload, matching the live browser request exactly.

        The OutSystems SearchPage screen is fussy: the search term is ``SearchKeyword``
        (not ``SearchTerm``), ``IsSearch`` must be True, pagination is ``PageNumber`` /
        ``URLPageNumber``, and the full variable set must be present or the server
        returns 12 unavailable dummy skeletons. Results come back in ``ProductList_All``.
        ``page_size`` is unused — the server fixes the page size.
        """
        return {
            "versionInfo": self._session.version_info_for_search(),
            "viewName": "MainFlow.SearchPage",
            "screenData": {
                "variables": {
                    "AppliedFiltersList": {
                        "List": [],
                        "EmptyListItem": {
                            "Name": "",
                            "Quantity": "0",
                            "IsSelected": False,
                            "URL": "",
                        },
                    },
                    "LocalCategoryID": 0,
                    "LocalCategoryName": "",
                    "LocalCategoryParentId": 0,
                    "LocalCategoryTitle": "",
                    "IsLoadingMore": page > 1,
                    "IsFirstDataFetched": False,
                    "ShowFilters": False,
                    "IsShowData": False,
                    "StoreNumber": store_number,
                    "StoreChannel": _CHANNEL_ID,
                    "CheckoutId": self._session.checkout_id,
                    "IsOrderEditMode": False,
                    "ProductList_All": {"List": [], "EmptyListItem": _SEARCH_EMPTY_ITEM},
                    "PageNumber": page,
                    "SelectedSort": "",
                    "OrderEditId": "",
                    "IsListRendered": False,
                    "IsAlreadyFetch": False,
                    "IsPromotionBannersFetched": False,
                    "Period": self._promo_week(),
                    "UserStoreId": self._session.user_store_id,
                    "FilterExpandedList": {"List": [], "EmptyListItem": False},
                    "ItemsInCart": {"List": []},
                    "HideDummy": False,
                    "OneWelcomeUserId": self._session.onewelcome_user_id,
                    "_oneWelcomeUserIdInDataFetchStatus": 1,
                    "CategorySlug": "",
                    "_categorySlugInDataFetchStatus": 1,
                    "SearchKeyword": query,
                    "_searchKeywordInDataFetchStatus": 1,
                    "IsDesktop": True,
                    "_isDesktopInDataFetchStatus": 1,
                    "IsSearch": True,
                    "_isSearchInDataFetchStatus": 1,
                    "URLPageNumber": page,
                    "_uRLPageNumberInDataFetchStatus": 1,
                    "FilterQueryURL": "",
                    "_filterQueryURLInDataFetchStatus": 1,
                    "IsMobile": False,
                    "_isMobileInDataFetchStatus": 1,
                    "IsTablet": False,
                    "_isTabletInDataFetchStatus": 1,
                    "Monitoring_FlowTypeId": 2,
                    "_monitoring_FlowTypeIdInDataFetchStatus": 1,
                    "IsCustomerUnderAge": False,
                    "_isCustomerUnderAgeInDataFetchStatus": 1,
                }
            },
        }

    async def get_all_products_api(
        self,
        store_number: int | None = None,
        max_pages: int = 1200,
    ) -> list["Product"]:
        """
        Download the full store catalogue via the PLP search endpoint.

        Pages through DataActionGetProductListAndCategoryInfo with an empty
        SearchKeyword — which returns the complete product list for the store
        (~11k products, 12 per page) — and accumulates every product. Direct API
        only; no per-product browser navigation.

        Loop length is driven by the server's TotalPages; dedupes by SKU and stops
        early on an empty page or one that adds nothing new (defensive against the
        server clamping the page number).
        """
        import time as _time

        effective_store = store_number or self._session.store_number

        if not self._session.search_api_version:
            print("[*] search apiVersion onbekend — navigeer naar zoekresultaten…")
            await self._page.goto(f"{_SEARCH_PAGE_URL}melk")
            await self._page.wait_for_load_state("networkidle", timeout=25_000)
            await asyncio.sleep(1)

        by_sku: dict[str, Product] = {}
        page = 1
        total_pages = max_pages
        t_all = _time.perf_counter()

        while page <= min(total_pages, max_pages):
            payload = self._build_search_payload("", effective_store, page=page)
            result = await self._page.evaluate(
                """async (payload) => {
                    const cookieMap = {};
                    document.cookie.split('; ').forEach(c => {
                        const eq = c.indexOf('=');
                        if (eq > 0) cookieMap[c.slice(0, eq)] = c.slice(eq + 1);
                    });
                    const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
                    const crf = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
                    const csrfToken = crf.slice(crf.indexOf('=') + 1);
                    const resp = await fetch(
                        'https://www.plus.nl/screenservices/ECP_Composition_CW/ProductLists'
                        + '/PLP_Content/DataActionGetProductListAndCategoryInfo',
                        {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'x-csrftoken': csrfToken,
                                'outsystems-locale': 'nl-NL',
                            },
                            body: JSON.stringify(payload),
                            credentials: 'include',
                        }
                    );
                    if (!resp.ok) throw new Error('HTTP ' + resp.status);
                    return await resp.json();
                }""",
                payload,
            )

            vi = result.get("versionInfo", {})
            if vi.get("hasApiVersionChanged"):
                self._session.search_api_version = ""
                version_cache.save_from_session(self._session)
                raise RuntimeError("hasApiVersionChanged — cache gewist, herstart sessie")

            data = result.get("data", {})
            if page == 1:
                total_pages = int(data.get("TotalPages") or 0) or max_pages
                print(
                    f"[API] catalogue: {data.get('TotalNumberItems')} products "
                    f"across {total_pages} pages"
                )

            products = _parse_search_results(data, effective_store)
            if not products:
                break

            new_on_page = 0
            for p in products:
                if p.sku and p.sku not in by_sku:
                    by_sku[p.sku] = p
                    new_on_page += 1

            if page % 50 == 0 or page == 1:
                print(f"[API] catalogue page {page}/{total_pages}: {len(by_sku)} products so far")

            if new_on_page == 0:
                break
            page += 1

        print(
            f"[API] catalogue download: {len(by_sku)} products in "
            f"{(_time.perf_counter() - t_all):.1f}s"
        )
        return list(by_sku.values())

    def _build_purchase_history_payload(self, page: int, page_size: int) -> dict:
        import datetime as _dt

        # Period is required by the schema but ignored by the server — current
        # promo week is what the browser sends; server returns all-time history.
        today = _dt.date.today()
        week_start = today - _dt.timedelta(days=today.weekday() + 2)  # approx Mon
        week_end = week_start + _dt.timedelta(days=6)
        return {
            "versionInfo": self._session.version_info_for_purchase_history(),
            "viewName": "AccountFlow.RecentlyBoughtProducts",
            "screenData": {
                "variables": {
                    "UserStoreChannelId": _CHANNEL_ID,
                    "CheckoutOrderInfo": {
                        "CheckoutId": self._session.checkout_id,
                        "OrderEditId": "",
                        "IsOrderEditMode": False,
                    },
                    "CurrentPageNumber": page,
                    "ProductList": {
                        "List": [],
                        "EmptyListItem": _PURCHASE_HISTORY_EMPTY_ITEM,
                    },
                    "NumberOfProductsPerPage": page_size,
                    "FromTime": _dt.datetime.now().strftime("%H:%M:%S"),
                    "Period": {
                        "FromDate": week_start.isoformat(),
                        "ToDate": week_end.isoformat(),
                    },
                    "UserStoreId": self._session.user_store_id,
                    "IsUnderAge": False,
                    "IsInitialDataFetched": False,
                    "IsDesktop": True,
                    "_isDesktopInDataFetchStatus": 1,
                    "IsTablet": False,
                    "_isTabletInDataFetchStatus": 1,
                    "IsPhone": False,
                    "_isPhoneInDataFetchStatus": 1,
                    "OneWelcomeUserId": self._session.onewelcome_user_id,
                    "_oneWelcomeUserIdInDataFetchStatus": 1,
                }
            },
        }

    def _build_promotions_payload(self, next_week: bool = False) -> dict:
        cart_items = [
            {"LineItemId": lid, "SKU": sku, "Quantity": 0}
            for sku, lid in self._session.line_item_ids.items()
        ]
        return {
            "versionInfo": self._session.version_info_for_promotions(),
            "viewName": "MainFlow.Promotions",
            "screenData": {
                "variables": {
                    "IsShowData": False,
                    "IsPreloadedHTMLActive": False,
                    "StoreNumber": self._session.store_number,
                    "StoreChannel": _CHANNEL_ID,
                    "PromotionPeriodId": 1,
                    "LocalPromotionList": {"List": [], "EmptyListItem": _PROMO_EMPTY_ITEM},
                    "ItemExistsInCart": {"List": cart_items},
                    "IsAppedingRecords": False,
                    "StartIndex": 0,
                    "MaxRecords": 1,
                    "IsDesktop": True,
                    "_isDesktopInDataFetchStatus": 1,
                    "IsTablet": False,
                    "_isTabletInDataFetchStatus": 1,
                    "IsPhone": False,
                    "_isPhoneInDataFetchStatus": 1,
                    "OneWelcomeUserId": self._session.onewelcome_user_id,
                    "_oneWelcomeUserIdInDataFetchStatus": 1,
                    "IsCustomerUnderAge": False,
                    "_isCustomerUnderAgeInDataFetchStatus": 1,
                    "UserStoreId": self._session.user_store_id,
                    "_userStoreIdInDataFetchStatus": 1,
                    "IsTimetraveler": False,
                    "_isTimetravelerInDataFetchStatus": 1,
                    "IsNextWeekPromotions": next_week,
                    "_isNextWeekPromotionsInDataFetchStatus": 1,
                }
            },
        }

    async def prime_remove_api(self) -> bool:
        """
        Navigate to cart, open the quantity slider on the first item, click
        the remove button once. This captures:
        - cart_remove_api_version (from the intercepted request)
        - LineItemIds for every item in the cart (from the request body)

        The first item loses 1 unit. Returns True if apiVersion was captured.
        """
        await self._page.goto(_CART_URL)
        await self._page.wait_for_load_state("networkidle", timeout=15_000)
        await self._decline_cookies_if_present()

        # Click quantity badge to open the ±-slider
        await self._page.evaluate("document.querySelector('a.gtm-quantity-clicked')?.click()")
        await asyncio.sleep(0.8)

        # Click remove (decrements first item by 1)
        await self._page.evaluate("document.querySelector('button.gtm-remove-from-cart')?.click()")

        # Poll until _on_request captures the version (max 5 s)
        deadline = asyncio.get_event_loop().time() + 5
        while (
            not self._session.cart_remove_api_version and asyncio.get_event_loop().time() < deadline
        ):
            await asyncio.sleep(0.2)

        return bool(self._session.cart_remove_api_version)

    async def remove_from_cart_api(self, sku: str, quantity: int = 1) -> dict:
        """
        Remove `quantity` units of `sku` from the cart via direct API call.

        Requires cart_remove_api_version and a known LineItemId for this SKU.
        Call prime_remove_api() first if either is missing, or ensure
        add_to_cart_api() was called for this SKU (which populates line_item_ids).
        """
        import json as _json
        import time as _time

        if not self._session.cart_remove_api_version:
            print("[*] remove apiVersion onbekend — prime_remove_api() uitvoeren…")
            await self.prime_remove_api()

        line_item_id = self._session.line_item_ids.get(sku)
        if not line_item_id:
            raise ValueError(
                f"LineItemId voor SKU {sku} onbekend. "
                "Roep prime_remove_api() aan of voeg het item toe via add_to_cart_api()."
            )

        payload = {
            "versionInfo": self._session.version_info_for_remove(),
            "viewName": "MainFlow.Cart",
            "inputParameters": {
                "IsOrderEditMode": False,
                "CheckoutId": self._session.checkout_id,
                "CheckoutVersion": self._session.checkout_version,
                "OrderEditId": "",
                "LineItemId": line_item_id,
                "QuantityToRemove": quantity,
                "SKU": sku,
                "ChannelId": "1690b994-7511-41cc-a1bc-aacf2726f218",
                "OneWelcomeUserId": self._session.onewelcome_user_id,
            },
        }

        t0 = _time.perf_counter()
        result = await self._page.evaluate(
            """async (payload) => {
                const cookieMap = {};
                document.cookie.split('; ').forEach(c => {
                    const eq = c.indexOf('=');
                    if (eq > 0) cookieMap[c.slice(0, eq)] = c.slice(eq + 1);
                });
                const nr2 = decodeURIComponent(cookieMap['nr2Users'] || '');
                const crfField = nr2.split(';').find(p => p.trim().startsWith('crf=')) || '';
                const csrfToken = crfField.slice(crfField.indexOf('=') + 1);

                const resp = await fetch(
                    'https://www.plus.nl/screenservices/ECP_Cart_CW/ActionCheckoutItem_Remove',
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'x-csrftoken': csrfToken,
                            'outsystems-locale': 'nl-NL'
                        },
                        body: JSON.stringify(payload),
                        credentials: 'include'
                    }
                );
                if (!resp.ok) {
                    const body = await resp.text().catch(() => '');
                    throw new Error('HTTP ' + resp.status + ' — ' + body.slice(0, 300));
                }
                return JSON.stringify(await resp.json());
            }""",
            payload,
        )
        elapsed = _time.perf_counter() - t0
        print(f"[API] ActionCheckoutItem_Remove → 200 in {elapsed * 1000:.0f}ms")

        data = _json.loads(result)
        checkout = data["data"]["Checkout"]
        self._session.checkout_version = checkout["Version"]
        self._update_line_item_ids(checkout)
        return checkout

    async def get_session_state(self) -> SessionState:
        """
        Return the session state captured from intercepted requests.
        Call this after login — the page's automatic screenservices calls
        will have populated module_version, checkout_id, etc.
        Always navigates to the cart page so DataActionGetCartById fires,
        capturing a fresh cart_get_api_version and priming the cart.
        """
        import logging as _logging

        _log = _logging.getLogger(__name__)

        _log.info("get_session_state — navigeren naar winkelwagen (%s)", _CART_URL)
        await self._page.goto(_CART_URL)
        _log.info("get_session_state — wachten op networkidle")
        await self._page.wait_for_load_state("networkidle", timeout=15_000)
        _log.info("get_session_state — networkidle bereikt; versiecache laden")

        # Load cached apiVersions — only fills fields not already captured above
        version_cache.apply_to_session(self._session)

        # Give pending _parse_cart_response futures a chance to complete.
        # We do not await _cart_parse_task explicitly — it may block indefinitely
        # if Playwright can't read the response body.  get_cart_api() will use
        # _primed_cart opportunistically if it's ready, or fall back to a fresh
        # fetch (which now works because cart_get_api_version was just captured).
        await asyncio.sleep(0)
        _log.info(
            "get_session_state — asyncio.sleep(0) done; primed_cart=%s",
            self._primed_cart is not None,
        )

        self._session.cookies = await self.get_cookies_as_dict()

        cart_mv = self._session.cart_module_version or "(not yet captured)"
        if self._session.ready:
            print(
                f"[+] Session state captured: checkout_id={self._session.checkout_id[:8]}… "
                f"version={self._session.checkout_version} "
                f"cart_module_version={cart_mv[:12]}…"
            )
        else:
            missing = [
                k for k in ("checkout_id", "onewelcome_user_id") if not getattr(self._session, k)
            ]
            if not (self._session.cart_module_version or self._session.module_version):
                missing.append("module_version")
            print(f"[~] Session state incomplete, missing: {missing}")

        return self._session

    def print_api_discoveries(self) -> None:
        """Print all API calls captured during this session — useful for hardcoding endpoints."""
        if not self._api_calls:
            print("\n[API] No internal API calls captured during this session.")
            return
        seen: set[str] = set()
        unique = []
        for c in self._api_calls:
            key = f"{c['method']} {c['url'].split('?')[0]}"
            if key not in seen:
                seen.add(key)
                unique.append(c)
        print(f"\n[API] Discovered {len(unique)} unique API endpoint(s):")
        for c in unique:
            status = c.get("status", "?")
            bearer = "  [Bearer captured]" if c.get("bearer_captured") else ""
            print(f"  {c['method']:6} {status}  {c['url']}{bearer}")
        if self._bearer_token:
            print(f"\n[API] Bearer token (first 40 chars): {self._bearer_token[:40]}…")

    # ------------------------------------------------------------------
    # Cookie consent dialog
    # ------------------------------------------------------------------

    async def _decline_cookies_if_present(self) -> None:
        """Dismiss the PLUS.nl cookie wall if it is blocking the page."""
        try:
            dialog = await self._page.query_selector('[aria-label="De cookies van PLUS"]')
            if not dialog:
                return
            # Click "Weigeren" (decline) — same as the R decline_cookies() helper
            await self._page.get_by_text("Weigeren", exact=True).click(timeout=4_000)
            await self._page.wait_for_selector(
                '[aria-label="De cookies van PLUS"]', state="hidden", timeout=5_000
            )
            print("[*] Cookie dialog weggeklikt")
        except Exception:
            pass  # dialog not present or already gone

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(self, email: str, password: str) -> bool:
        """Login to PLUS.nl via the OAuth2 browser flow."""
        print("[*] Navigating to login page…")
        await self._page.goto(_LOGIN_URL)

        # If already logged in the session cookies may redirect us straight to plus.nl
        if "plus.nl" in self._page.url and "aanmelden" not in self._page.url:
            print("[+] Already logged in (session cookie active)")
            return True

        # Wait for login form fields
        try:
            await self._page.wait_for_selector("#username", timeout=12_000)
        except Exception:
            print("[-] Login form not found — PLUS.nl may have changed their login page")
            return False

        await self._page.fill("#username", email)
        await self._page.fill("#password", password)
        _local, _, _domain = email.partition("@")
        log.debug(
            "[*] Submitting credentials for %s…", f"{_local[:1]}***@{_domain}" if _domain else "***"
        )
        await self._page.click("#loginFormUsernameAndPasswordButton")

        # Wait for redirect back to plus.nl
        try:
            await self._page.wait_for_url("https://www.plus.nl/**", timeout=20_000)
        except Exception:
            print("[-] Did not redirect to plus.nl — login may have failed")
            return False

        # Dismiss cookie dialog that appears on the first post-login page
        await self._decline_cookies_if_present()

        # Confirm logged-in indicator appears
        try:
            await self._page.wait_for_selector(
                ".gtm-account-options .popover-top-label span",
                timeout=10_000,
            )
            log.debug("[+] Logged in (account indicator confirmed)")
            return True
        except Exception:
            # The selector might have changed; check URL as fallback
            if "plus.nl" in self._page.url and "aanmelden" not in self._page.url:
                print(f"[+] Logged in (redirected to {self._page.url})")
                return True
            print("[-] Login appeared to succeed but could not confirm account indicator")
            return False

    # ------------------------------------------------------------------
    # Add to cart
    # ------------------------------------------------------------------

    async def add_to_cart(self, sku: str, quantity: int = 1) -> bool:
        """
        Add `quantity` units of `sku` to the PLUS.nl cart.

        Uses the search page so any valid SKU works without knowing the
        full product URL slug.  Playwright waits for actual network idle
        between clicks, which is faster and more reliable than the R
        implementation's fixed `Sys.sleep(2)` per click.
        """
        search_url = f"https://www.plus.nl/zoekresultaten?SearchTerm={sku}"
        print(f"[*] Navigating to search page for SKU {sku}…")
        await self._page.goto(search_url)

        try:
            await self._page.wait_for_selector("button.gtm-add-to-cart", timeout=15_000)
        except Exception:
            print(f"[-] Add-to-cart button not found for SKU {sku}")
            return False

        # Cookie dialog may reappear on search result pages
        await self._decline_cookies_if_present()
        # Let the page settle after any overlay animation
        await self._page.wait_for_load_state("networkidle", timeout=8_000)

        # Read cart count before adding
        before = await self._cart_badge_count()

        for i in range(quantity):
            # Use JavaScript click — same as the R code's Runtime.evaluate("...click()").
            # Playwright's native click() checks for intercepting overlays (quantity wrapper
            # divs, sticky header) and times out; JS click fires directly on the element.
            clicked = await self._page.evaluate(
                "document.querySelector('button.gtm-add-to-cart')?.click(); "
                "!!document.querySelector('button.gtm-add-to-cart')"
            )
            if not clicked:
                print(f"[-] Add-to-cart button disappeared during click {i + 1}")
                break

            # Wait for badge count to increase (the cart API call completed)
            try:
                await self._page.wait_for_function(
                    f"() => {{"
                    f"  const badge = document.querySelector('.cart-badge-link .badge');"
                    f"  return badge && parseInt(badge.textContent.trim() || '0') >= {before + i + 1};"
                    f"}}",
                    timeout=10_000,
                )
            except Exception:
                # Badge selector may differ or cart was empty before; wait for network idle
                await self._page.wait_for_load_state("networkidle", timeout=8_000)

        after = await self._cart_badge_count()
        added = after - before
        if added == quantity:
            print(f"[+] Added {added}/{quantity} × SKU {sku} to cart")
            return True
        else:
            print(f"[~] Added {added}/{quantity} × SKU {sku} (badge count mismatch, check cart)")
            return added > 0

    async def _cart_badge_count(self) -> int:
        el = await self._page.query_selector(".cart-badge-link .badge")
        if not el:
            return 0
        text = (await el.inner_text()).strip()
        try:
            return int(text)
        except ValueError:
            return 0

    # ------------------------------------------------------------------
    # Get cart
    # ------------------------------------------------------------------

    async def get_cart(self) -> Cart:
        """Fetch and parse the current PLUS.nl cart."""
        print("[*] Loading cart page…")
        await self._page.goto(_CART_URL)
        await self._page.wait_for_load_state("networkidle", timeout=15_000)

        # Confirm the cart page has loaded
        try:
            await self._page.wait_for_selector(".cart-title-wrapper h1", timeout=10_000)
        except Exception:
            pass  # Page may still be parseable

        items_els = await self._page.query_selector_all(".cart-item-wrapper")
        items: list[CartItem] = []

        for el in items_els:
            name_el = await el.query_selector(".cart-item-name span")
            unit_el = await el.query_selector(".cart-item-complementary span")
            price_el = await el.query_selector(".cart-item-price span")
            qty_el = await el.query_selector(".cart-item-quantity span")

            if not name_el:
                continue

            name = (await name_el.inner_text()).strip()
            unit = (await unit_el.inner_text()).strip() if unit_el else ""
            qty_text = (await qty_el.inner_text()).strip() if qty_el else "1"
            price_text = (await price_el.inner_text()).strip() if price_el else "0"

            price = _parse_price(price_text)
            qty = _parse_int(qty_text)

            if name:
                items.append(CartItem(product=name, unit=unit, price=price, quantity=qty))

        # Parse final total
        total_el = await self._page.query_selector(".total-receipt-item")
        total_text = (await total_el.inner_text()).strip() if total_el else "0"
        final_total = _parse_price(total_text)

        return Cart(items=items, final_total=final_total)

    # ------------------------------------------------------------------
    # Helpers for cookie-based httpx sessions (future direct API use)
    # ------------------------------------------------------------------

    async def get_cookies_as_dict(self) -> dict[str, str]:
        """Return current browser cookies — can be passed to httpx for direct API calls."""
        cookies = await self._context.cookies()
        return {c["name"]: c["value"] for c in cookies}


# ------------------------------------------------------------------
# Parsing helpers
# ------------------------------------------------------------------


def _parse_purchased_products(data: dict) -> "list[PurchasedProduct]":
    result = []
    for item in data.get("Products", {}).get("List", []):
        img = item.get("ImageURL", "")
        if img.startswith("//"):
            img = "https:" + img
        categories = [
            c.get("Name", "") for c in item.get("Categories", {}).get("List", []) if c.get("Name")
        ]
        result.append(
            PurchasedProduct(
                sku=item.get("SKU", ""),
                brand=item.get("Brand", ""),
                name=item.get("Name", ""),
                subtitle=item.get("Product_Subtitle", ""),
                slug=item.get("Slug", ""),
                image_url=img,
                price=_safe_float(item.get("OriginalPrice", "0")),
                is_available=item.get("IsAvailable", False),
                categories=categories,
            )
        )
    return result


def _parse_promotion_products(data: dict) -> "list[PromotionProduct]":
    products = []
    for item in data.get("PromotionOfferDetail", {}).get("ProductList", {}).get("List", []):
        p = item.get("PLP_Str", {})
        img = p.get("ImageURL", "")
        if img.startswith("//"):
            img = "https:" + img
        products.append(
            PromotionProduct(
                sku=p.get("SKU", ""),
                brand=p.get("Brand", ""),
                name=p.get("Name", ""),
                subtitle=p.get("Product_Subtitle", ""),
                slug=p.get("Slug", ""),
                image_url=img,
                price_original=_safe_float(item.get("Price_Original", "0")),
                price_new=_safe_float(p.get("NewPrice", "0")),
                label=item.get("DisplayInfo_Label", ""),
                is_available=p.get("IsAvailable", False),
                max_order_limit=p.get("MaxOrderLimit", 0),
            )
        )
    return products


def _parse_promotion_result(data: dict) -> "PromotionResult":
    period = data.get("PromotionPeriod", {})
    promotions: list[Promotion] = []

    for section in data.get("PromotionOfferList", {}).get("List", []):
        cat = section.get("Category", {})
        cat_id = cat.get("CategoryId", "")
        cat_label = cat.get("CategoryLabel", "")

        for offer in cat.get("Offers", {}).get("List", []):
            img = offer.get("ImageURL", "")
            if img.startswith("//"):
                img = "https:" + img

            promotions.append(
                Promotion(
                    category_id=cat_id,
                    category_label=cat_label,
                    slug=offer.get("Slug", ""),
                    brand=offer.get("Brand", ""),
                    name=offer.get("Name", ""),
                    subtitle=offer.get("Example", ""),
                    variant=offer.get("Variant", ""),
                    label=offer.get("DisplayInfo_Label", ""),
                    price_new=_safe_float(offer.get("NewPrice", "0")),
                    price_was=_safe_float(offer.get("PriceOriginal_Lowest", "0")),
                    start_date=offer.get("StartDate", ""),
                    end_date=offer.get("EndDate", ""),
                    sku=offer.get("Product_SKU", ""),
                    image_url=img,
                    is_free_delivery=offer.get("IsFreeDeliveryOffer", False),
                    is_single_product=offer.get("IsSingleProduct", False),
                )
            )

    return PromotionResult(
        period_from=period.get("FromDate", ""),
        period_to=period.get("ToDate", ""),
        is_next_week_published=data.get("IsNextWeekPublished", False),
        promotions=promotions,
    )


def _parse_search_results(data: dict, store_number: int = 0) -> list["Product"]:
    """
    Parse search response into Product list.

    Tries multiple response key paths defensively since the exact structure
    is inferred (run explore_search.py to confirm against a live session).
    """
    # Try the most likely paths first. The live SearchPage returns results in
    # ProductList_All; older/other shapes use ProductList.
    raw = (
        data.get("ProductList_All", {}).get("List")
        or data.get("ProductList", {}).get("List")
        or data.get("ProductListAndCategoryInfo", {}).get("ProductList", {}).get("List")
        or []
    )
    # Fall back: walk top-level keys looking for something with a List of SKU-like items
    if not raw:
        for v in data.values():
            if isinstance(v, dict):
                lst = v.get("ProductList", {}).get("List") or v.get("List", [])
                if isinstance(lst, list) and lst and isinstance(lst[0], dict) and "SKU" in lst[0]:
                    raw = lst
                    break

    products = []
    for item in raw:
        # Live SearchPage wraps each product's fields in PLP_Str; older shapes are flat.
        p = item.get("PLP_Str") if isinstance(item.get("PLP_Str"), dict) else item
        sku = p.get("SKU") or ""
        if not sku:
            continue  # skip dummy/skeleton rows
        img = p.get("ImageURL") or ""
        if img.startswith("//"):
            img = "https:" + img
        categories = [
            c.get("Name", "") for c in (p.get("Categories") or {}).get("List", []) if c.get("Name")
        ]
        products.append(
            Product(
                sku=sku,
                name=p.get("Name") or "",
                subtitle=p.get("Product_Subtitle") or "",
                brand=p.get("Brand") or "",
                slug=p.get("Slug") or "",
                image_url=img,
                price=_safe_float(p.get("OriginalPrice") or p.get("NewPrice") or "0"),
                is_available=bool(p.get("IsAvailable")),
                store_number=store_number,
                categories=categories,
            )
        )
    return products


def _parse_cart_from_checkout(checkout: dict) -> "Cart":
    """Parse a Checkout dict (from any cart API response) into a Cart model."""
    items = []
    for line in checkout.get("LineItemList", {}).get("List", []):
        img = line.get("ImageURL", "")
        if img.startswith("//"):
            img = "https:" + img
        items.append(
            CartItem(
                product=line.get("Name", ""),
                unit=line.get("Subtitle", ""),
                price=_safe_float(line.get("Price", "0")),
                quantity=line.get("Quantity", 0),
                sku=line.get("SKU", ""),
                image_url=img,
                line_item_id=line.get("LineItemId", ""),
            )
        )
    receipt = checkout.get("Receipt", {})
    total = _safe_float(receipt.get("Price", "0"))
    # Statiegeld (deposit) — added on top of the product/discount total; reported
    # under Receipt.DepositFeeCosts. Kept separate so the UI can distinguish it
    # from the promotional korting below.
    deposit = _safe_float(receipt.get("DepositFeeCosts", "0"))
    # Promotional discount (korting). PLUS reports it under Receipt.DiscountedPrice
    # (older responses used Discount). When neither is present, derive it from the
    # gross (sum of full line prices) minus the *product* net — i.e. the total with
    # the deposit fee removed, since deposit inflates the charged total but is not a
    # discount. That gross-minus-net delta is the discount applied.
    explicit = _safe_float(receipt.get("DiscountedPrice", "0")) or _safe_float(
        receipt.get("Discount", "0")
    )
    gross = round(sum(it.price_total for it in items), 2)
    savings = explicit if explicit > 0 else max(0.0, round(gross - (total - deposit), 2))
    return Cart(items=items, final_total=total, savings=savings, deposit=deposit)


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_price(text: str) -> float:
    """Extract a float price from strings like '€ 1,99', '1.99', '2,50'."""
    cleaned = re.sub(r"[^\d,.]", "", text).replace(",", ".")
    # Remove leading/trailing dots
    cleaned = cleaned.strip(".")
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_int(text: str) -> int:
    m = re.search(r"\d+", text)
    return int(m.group()) if m else 0
