"""Unit tests for per-row deal-total computation (strikethrough prices)."""

from plus.models import Promotion
from pyplus.ui.components.cart import _compute_deal_total


def _promo(label="", *, price_new=0.0, price_was=0.0, single=False, fd=False):
    return Promotion(
        category_id="",
        category_label="",
        slug="x",
        brand="",
        name="",
        subtitle="",
        variant="",
        label=label,
        price_new=price_new,
        price_was=price_was,
        start_date="",
        end_date="",
        sku="123" if single else "",
        image_url="",
        is_free_delivery=fd,
        is_single_product=single,
    )


class _Item:
    def __init__(self, price, quantity):
        self.price = price
        self.quantity = quantity


class TestVoor:
    def test_exact_match(self):
        assert _compute_deal_total(_promo("2 VOOR 2.49"), _Item(1.99, 2)) == 2.49

    def test_double_deal(self):
        assert _compute_deal_total(_promo("2 VOOR 2.49"), _Item(1.99, 4)) == 4.98

    def test_partial_remainder(self):
        assert _compute_deal_total(_promo("2 VOOR 2.49"), _Item(1.99, 3)) == 4.48

    def test_qty_below_deal(self):
        assert _compute_deal_total(_promo("2 VOOR 2.49"), _Item(1.99, 1)) is None

    def test_three_voor(self):
        assert _compute_deal_total(_promo("3 VOOR 5.00"), _Item(2.49, 3)) == 5.00

    def test_comma_decimal(self):
        assert _compute_deal_total(_promo("2 VOOR 2,49"), _Item(1.99, 2)) == 2.49


class TestGratis:
    def test_one_plus_one(self):
        assert _compute_deal_total(_promo("1+1 GRATIS"), _Item(1.99, 2)) == 1.99

    def test_one_plus_one_odd(self):
        assert _compute_deal_total(_promo("1+1 GRATIS"), _Item(1.99, 3)) == 3.98

    def test_two_plus_three(self):
        # buy 2, get 3 free → pay for 2 out of every 5
        assert _compute_deal_total(_promo("2+3 GRATIS"), _Item(5.00, 5)) == 10.00

    def test_two_plus_one_partial(self):
        # buy 2, get 1 free with qty=4: 1 full deal (pay 2) + 1 remainder (pay 1)
        assert _compute_deal_total(_promo("2+1 GRATIS"), _Item(3.00, 4)) == 9.00

    def test_qty_below_deal(self):
        assert _compute_deal_total(_promo("1+1 GRATIS"), _Item(1.99, 1)) is None


class TestKorting:
    def test_25_pct(self):
        assert _compute_deal_total(_promo("25% KORTING"), _Item(4.00, 1)) == 3.00

    def test_50_pct(self):
        assert _compute_deal_total(_promo("50% KORTING"), _Item(2.00, 3)) == 3.00


class TestSingleProductFallback:
    def test_uses_price_new(self):
        p = _promo(price_new=2.69, price_was=4.99, single=True)
        assert _compute_deal_total(p, _Item(4.99, 2)) == 5.38

    def test_no_discount(self):
        p = _promo(price_new=4.99, price_was=4.99, single=True)
        assert _compute_deal_total(p, _Item(4.99, 1)) is None


class TestEdgeCases:
    def test_none_promo(self):
        assert _compute_deal_total(None, _Item(1.99, 2)) is None

    def test_free_delivery_skipped(self):
        assert _compute_deal_total(_promo("2 VOOR 2.49", fd=True), _Item(1.99, 2)) is None

    def test_unknown_label(self):
        assert _compute_deal_total(_promo("NIEUW"), _Item(1.99, 2)) is None
