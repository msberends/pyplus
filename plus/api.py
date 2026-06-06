"""
Direct httpx API client for PLUS.nl cart operations.

All state (module_version, checkout_id, etc.) must be captured from a
browser session first (via PlusClient.session_state), then passed here.
The browser is only needed for the OAuth2 login — every cart operation
after that is a single POST call, taking ~200ms instead of ~10s.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from .models import Cart, CartItem

SCREENSERVICES = "https://www.plus.nl/screenservices"
CHANNEL_ID = "1690b994-7511-41cc-a1bc-aacf2726f218"  # web channel — stable


@dataclass
class SessionState:
    """Values captured from the browser session after login."""

    module_version: str = ""  # generic (first seen) — may come from any module
    api_version: str = ""
    cart_module_version: str = ""  # specifically from ECP_Cart_CW requests
    cart_api_version: str = ""
    cart_add_api_version: str = ""  # specifically from ActionCheckoutItem_Add
    cart_remove_api_version: str = ""  # from ActionCheckoutItem_Remove
    cart_get_api_version: str = ""  # from DataActionGetCartById
    promotions_api_version: str = ""  # from DataActionGetPromotionList_Optimization
    promo_detail_api_version: str = ""  # from DataActionPromotionOfferDetail_Get
    purchase_history_api_version: str = ""  # from RecentlyBoughtProducts/DataActionGetProducts
    order_list_api_version: str = ""  # from OrdersContent/DataActionGetCustomerDetails
    order_detail_api_version: str = ""  # from OrderDetailsContent/DataActionGetOrderDetails
    search_api_version: str = (
        ""  # from ProductLists/PLP_Content/DataActionGetProductListAndCategoryInfo
    )
    line_item_ids: dict = field(default_factory=dict)  # SKU → LineItemId
    checkout_id: str = ""
    checkout_version: int = 0
    onewelcome_user_id: str = ""
    store_number: int = 0  # from ActionStoreWrapper_GetGeneralDetails
    store_name: str = ""  # from ActionStoreWrapper_GetGeneralDetails (Store_Name)
    user_store_id: str = ""  # from ActionCustomerTemp_GetDetails.PreferredStoreId
    cookies: dict[str, str] = field(default_factory=dict)

    def version_info_for_cart(self) -> dict:
        return {
            "moduleVersion": self.cart_module_version or self.module_version,
            "apiVersion": self.cart_api_version or self.api_version,
        }

    def version_info_for_remove(self) -> dict:
        return {
            "moduleVersion": self.cart_module_version or self.module_version,
            "apiVersion": self.cart_remove_api_version or self.cart_api_version or self.api_version,
        }

    def version_info_for_add(self) -> dict:
        """Return the correct versionInfo for ActionCheckoutItem_Add.
        cart_add_api_version is captured from the first browser-based add-to-cart call."""
        return {
            "moduleVersion": self.cart_module_version or self.module_version,
            "apiVersion": self.cart_add_api_version or self.cart_api_version or self.api_version,
        }

    def version_info_for_promotions(self) -> dict:
        return {
            "moduleVersion": self.module_version,
            "apiVersion": self.promotions_api_version or self.api_version,
        }

    def version_info_for_promo_detail(self) -> dict:
        return {
            "moduleVersion": self.module_version,
            "apiVersion": self.promo_detail_api_version or self.api_version,
        }

    def version_info_for_order_list(self) -> dict:
        return {
            "moduleVersion": self.module_version,
            "apiVersion": self.order_list_api_version or self.api_version,
        }

    def version_info_for_order_detail(self) -> dict:
        return {
            "moduleVersion": self.module_version,
            "apiVersion": self.order_detail_api_version or self.api_version,
        }

    def version_info_for_search(self) -> dict:
        return {
            "moduleVersion": self.module_version,
            "apiVersion": self.search_api_version or self.api_version,
        }

    def version_info_for_get_cart(self) -> dict:
        return {
            "moduleVersion": self.cart_module_version or self.module_version,
            "apiVersion": self.cart_get_api_version or self.cart_api_version or self.api_version,
        }

    def version_info_for_purchase_history(self) -> dict:
        return {
            "moduleVersion": self.module_version,
            "apiVersion": self.purchase_history_api_version or self.api_version,
        }

    @property
    def ready(self) -> bool:
        return all(
            [
                self.cart_module_version or self.module_version,
                self.cart_api_version or self.api_version,
                self.checkout_id,
                self.onewelcome_user_id,
                self.cookies,
            ]
        )


class PlusDirectClient:
    """
    PLUS.nl cart client using direct httpx calls to the OutSystems screenservices API.

    Usage::

        state = await plus_browser_client.get_session_state()
        async with PlusDirectClient(state) as api:
            checkout = await api.add_to_cart("957806", quantity=2)
            print(f"Cart total: €{checkout['Receipt']['Price']}")
    """

    def __init__(self, state: SessionState):
        self._state = state
        self._http = httpx.AsyncClient(
            cookies=state.cookies,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://www.plus.nl",
                "Referer": "https://www.plus.nl/",
            },
            follow_redirects=True,
            timeout=15.0,
        )

    async def __aenter__(self) -> "PlusDirectClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self._http.aclose()

    def _version_info(self) -> dict:
        return {
            "moduleVersion": self._state.module_version,
            "apiVersion": self._state.api_version,
        }

    async def add_to_cart(self, sku: str, quantity: int = 1) -> dict:
        """
        Add items to the PLUS.nl cart via direct API call.
        Returns the Checkout dict from the response (contains cart state).
        Automatically updates checkout_version for the next call.
        """
        t0 = time.perf_counter()

        payload = {
            "versionInfo": self._version_info(),
            "viewName": "MainFlow.SearchPage",
            "inputParameters": {
                "IsOrderEditMode": False,
                "CheckoutId": self._state.checkout_id,
                "CheckoutVersion": self._state.checkout_version,
                "OrderEditId": "",
                "SKU": sku,
                "QuantityToAdd": quantity,
                "ChannelId": CHANNEL_ID,
                "OneWelcomeUserId": self._state.onewelcome_user_id,
            },
        }

        resp = await self._http.post(
            f"{SCREENSERVICES}/ECP_Cart_CW/ActionCheckoutItem_Add",
            json=payload,
        )
        elapsed = time.perf_counter() - t0
        resp.raise_for_status()

        data = resp.json()

        version_info = data.get("versionInfo", {})
        if version_info.get("hasModuleVersionChanged") or version_info.get("hasApiVersionChanged"):
            raise RuntimeError(
                "PLUS.nl deployed a new app version — re-login to refresh moduleVersion/apiVersion."
            )

        checkout = data["data"]["Checkout"]
        # Keep version in sync — must match for next call
        self._state.checkout_version = checkout["Version"]

        print(f"[API] ActionCheckoutItem_Add → {resp.status_code} in {elapsed * 1000:.0f}ms")
        return checkout

    def cart_from_checkout(self, checkout: dict) -> Cart:
        """Parse a Checkout dict (from add_to_cart response) into a Cart model."""
        items = []
        for line in checkout.get("LineItemList", {}).get("List", []):
            items.append(
                CartItem(
                    product=line.get("Name", ""),
                    unit=line.get("Subtitle", ""),
                    price=float(line.get("Price", 0)),
                    quantity=line.get("Quantity", 0),
                )
            )
        total = float(checkout.get("Receipt", {}).get("Price", 0))
        return Cart(items=items, final_total=total)
