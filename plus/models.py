from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, computed_field


class CartItem(BaseModel):
    product: str
    unit: str  # subtitle, e.g. "Per 650 g"
    price: float
    quantity: int
    # Extended fields — populated by get_cart_api() and add/remove responses
    sku: str = ""
    image_url: str = ""
    line_item_id: str = ""

    @computed_field
    @property
    def price_total(self) -> float:
        return round(self.price * self.quantity, 2)


class Cart(BaseModel):
    items: list[CartItem]
    final_total: float
    savings: float = 0.0  # promotional discount (korting); from Receipt.DiscountedPrice
    deposit: float = 0.0  # statiegeld included in final_total; from Receipt.DepositFeeCosts

    @property
    def total_items(self) -> int:
        return sum(i.quantity for i in self.items)

    def __str__(self) -> str:
        lines = [
            f"PLUS Winkelwagen — {len(self.items)} producten, {self.total_items} stuks",
            "-" * 62,
        ]
        for item in self.items:
            lines.append(f"  {item.quantity:>2}x  {item.product:<38}  €{item.price_total:>6.2f}")
        lines.append("-" * 62)
        lines.append(f"  Totaal:     €{self.final_total:>6.2f}")
        if self.savings > 0:
            lines.append(f"  Bespaard:  -€{self.savings:>6.2f}")
        if self.deposit > 0:
            lines.append(f"  Statiegeld: €{self.deposit:>6.2f}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------


@dataclass
class PromotionProduct:
    sku: str
    brand: str
    name: str
    subtitle: str  # "Per 520 g"
    slug: str
    image_url: str
    price_original: float  # pre-discount price (from outer Price_Original)
    price_new: float  # discounted price (PLP_Str.NewPrice, often 0 for group deals)
    label: str  # per-product deal label, e.g. "1+1 GRATIS"
    is_available: bool
    max_order_limit: int

    @property
    def url(self) -> str:
        return f"https://www.plus.nl/product/{self.slug}" if self.slug else ""


@dataclass
class Promotion:
    category_id: str
    category_label: str
    slug: str
    brand: str
    name: str  # product name — populated for single-product deals
    subtitle: str  # "Bijv. …" example sentence
    variant: str  # exception text, e.g. "M.U.V. losse ijsjes"
    label: str  # "1+1 GRATIS", "0.99 PER KILO", etc.
    price_new: float
    price_was: float  # PriceOriginal_Lowest from the API
    start_date: str
    end_date: str
    sku: str  # populated only when is_single_product is True
    image_url: str
    is_free_delivery: bool
    is_single_product: bool

    @property
    def url(self) -> str:
        return f"https://www.plus.nl/aanbiedingen/{self.slug}" if self.slug else ""


@dataclass
class OrderSummary:
    order_id: str  # UUID used in /order-details?OrderId=
    order_number: str  # human-readable order number
    delivery_date: str  # "2026-03-16"
    delivery_start: str  # "10:00"
    delivery_end: str  # "12:00"
    total_price: float
    status: str  # "Bezorgd", "Opgehaald", "In behandeling"
    channel: str  # "Web", "App"
    is_active: bool  # True = current/upcoming, False = past

    @property
    def url(self) -> str:
        return f"https://www.plus.nl/order-details?OrderId={self.order_id}"


@dataclass
class OrderLineItem:
    sku: str
    name: str
    subtitle: str
    slug: str
    quantity: int
    price: float
    category: str
    image_url: str
    available: bool  # False = was unavailable at time of delivery

    @property
    def url(self) -> str:
        return f"https://www.plus.nl/product/{self.slug}" if self.slug else ""


@dataclass
class OrderDetail:
    order_id: str
    order_number: str
    delivery_date: str
    store_name: str
    status: str
    address: str
    items: list["OrderLineItem"] = field(default_factory=list)


@dataclass
class PurchasedProduct:
    sku: str
    brand: str
    name: str
    subtitle: str  # "Per 1000 ml"
    slug: str
    image_url: str
    price: float  # OriginalPrice
    is_available: bool
    categories: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://www.plus.nl/product/{self.slug}" if self.slug else ""


@dataclass
class Product:
    """A single product returned by search_products_api."""

    sku: str
    name: str
    subtitle: str  # e.g. "Per 500 g"
    brand: str
    slug: str
    image_url: str
    price: float  # OriginalPrice (not promotional)
    is_available: bool
    store_number: int = 0
    categories: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://www.plus.nl/product/{self.slug}" if self.slug else ""


@dataclass
class PromotionResult:
    period_from: str
    period_to: str
    is_next_week_published: bool
    promotions: list[Promotion] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [
            f"PLUS Aanbiedingen {self.period_from} t/m {self.period_to}",
            f"({len(self.promotions)} aanbiedingen, volgende week: {'gepubliceerd' if self.is_next_week_published else 'nog niet'})",
            "-" * 62,
        ]
        current_cat = ""
        for p in self.promotions:
            if p.category_label != current_cat:
                current_cat = p.category_label
                lines.append(f"\n  {current_cat}")
            label = f"[{p.label}]" if p.label else ""
            name = p.name or p.brand
            lines.append(f"    {name:<40} {label}")
        return "\n".join(lines)
