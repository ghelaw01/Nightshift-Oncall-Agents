"""The team's existing tests. They pass on the code that shipped."""
import pytest

from orders.api import checkout
from orders.inventory import OutOfStock, reserve
from orders.money import format_cents
from orders.pricing import line_total, order_total


def test_line_total():
    assert line_total(250, 4) == 1000


def test_order_total_without_discount_or_tax():
    assert order_total([{"price_cents": 500, "qty": 2}]) == 1000


def test_reserve_too_many_raises():
    with pytest.raises(OutOfStock):
        reserve({"A": 1}, "A", 5)


def test_format_cents():
    assert format_cents(1234) == "$12.34"


def test_empty_cart_is_rejected():
    assert checkout({"items": []}, {}, lambda total: True)[0] == 400


def test_happy_checkout():
    status, body = checkout({"items": [{"sku": "A", "price_cents": 1000, "qty": 1}], "coupon": "FRIEND"},
                            {"A": 3}, lambda t: True)
    assert status == 200 and body["total_cents"] == 1080
