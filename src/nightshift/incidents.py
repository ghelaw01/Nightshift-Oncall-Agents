"""Production incidents with known answers.

Each real incident plants a regression in the orders service (a bad commit that shipped),
fires the alert and logs that would really show up, and keeps a hidden test the agents
never see. An incident counts as resolved only if the hidden test passes, the team's own
tests still pass, and the guardrails were respected.

Two incidents are noise: nothing is wrong with the code, and the right move is to change nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Incident:
    id: str
    title: str
    kind: str                      # "bug" or "noise"
    alert: dict
    logs: list[str]
    file: str = ""                 # where the regression is (ground truth)
    old: str = ""                  # the good code ...
    new: str = ""                  # ... and the bad code that shipped
    commit_message: str = ""       # the bad commit, as it appears in history
    hidden_test: str = ""
    severity: str = "high"         # expected triage severity: high | low
    tags: list[str] = field(default_factory=list)


INCIDENTS: list[Incident] = [
    Incident(
        "INC-101", "Revenue drop on coupon orders", "bug",
        {"name": "checkout_revenue_per_order_low", "service": "orders", "value": "-87%",
         "condition": "avg order value with coupon vs 7-day baseline", "since": "02:14 UTC"},
        ["02:15:03 INFO checkout ok order=88121 coupon=SAVE10 items=1 subtotal=10000 total_cents=0",
         "02:15:41 INFO checkout ok order=88122 coupon=None items=2 subtotal=4000 total_cents=4320",
         "02:16:10 INFO checkout ok order=88123 coupon=SAVE10 items=3 subtotal=2500 total_cents=0",
         "02:17:55 WARN support ticket #5512: 'my order was free??'"],
        "orders/pricing.py", "total_cents * percent // 100", "total_cents * percent // 10",
        "pricing: simplify discount math", severity="high",
        hidden_test="""
from orders.pricing import apply_discount, order_total
def test_hidden():
    assert apply_discount(10000, 10) == 9000
    assert apply_discount(999, 0) == 999
    assert order_total([{"price_cents": 1000, "qty": 1}], 10, 0.08) == 972
"""),
    Incident(
        "INC-102", "Spike in 409 OutOfStock on items that are in stock", "bug",
        {"name": "checkout_409_rate_high", "service": "orders", "value": "14%", "threshold": "1%",
         "since": "11:02 UTC"},
        ["11:02:10 WARN checkout 409 order=90211 error='SKU-77: wanted 1, have 1'",
         "11:02:44 WARN checkout 409 order=90215 error='SKU-12: wanted 3, have 3'",
         "11:03:01 INFO checkout ok order=90216 items=1",
         "11:04:20 WARN checkout 409 order=90219 error='SKU-77: wanted 2, have 2'"],
        "orders/inventory.py", "if qty > available:", "if qty >= available:",
        "inventory: guard against overselling", severity="high",
        hidden_test="""
import pytest
from orders.inventory import OutOfStock, reserve
def test_hidden():
    stock = {"A": 2}
    reserve(stock, "A", 2)
    assert stock["A"] == 0
    with pytest.raises(OutOfStock):
        reserve(stock, "A", 1)
"""),
    Incident(
        "INC-103", "Finance: tax collected below expected", "bug",
        {"name": "tax_reconciliation_mismatch", "service": "orders", "value": "-$1,284.17 over 24h",
         "since": "yesterday"},
        ["09:00:00 INFO finance-recon orders=18211 expected_tax=148,220.55 collected_tax=146,936.38",
         "09:00:00 INFO finance-recon sample order=77120 subtotal=1999 rate=0.08 tax=159 expected=160",
         "09:00:00 INFO finance-recon sample order=77131 subtotal=2499 rate=0.08 tax=199 expected=200"],
        "orders/pricing.py", "total_cents + round(total_cents * rate)", "total_cents + int(total_cents * rate)",
        "pricing: use int for tax cents", severity="high",
        hidden_test="""
from orders.pricing import add_tax
def test_hidden():
    assert add_tax(1999, 0.08) == 2159
    assert add_tax(2499, 0.08) == 2699
    assert add_tax(1000, 0.08) == 1080
"""),
    Incident(
        "INC-104", "Payment calls timing out; checkout p99 latency 9 minutes", "bug",
        {"name": "checkout_latency_p99_high", "service": "orders", "value": "541s", "threshold": "5s",
         "since": "16:40 UTC"},
        ["16:41:02 WARN payment retry attempt=6 sleeping=32.0s",
         "16:41:34 WARN payment retry attempt=7 sleeping=64.0s",
         "16:42:38 WARN payment retry attempt=8 sleeping=128.0s",
         "16:44:46 ERROR request timeout upstream=lb after=300s"],
        "orders/retry.py", "return min(cap, base * 2 ** attempt)", "return base * 2 ** attempt",
        "retry: remove redundant min()", severity="high",
        hidden_test="""
from orders.retry import backoff_seconds
def test_hidden():
    assert backoff_seconds(0) == 0.5
    assert backoff_seconds(3) == 4.0
    assert backoff_seconds(10) == 8.0
    assert backoff_seconds(20, cap=2.0) == 2.0
"""),
    Incident(
        "INC-105", "Valid coupon SAVE10 rejected; expired OLD5 accepted", "bug",
        {"name": "coupon_redemption_anomaly", "service": "orders", "value": "SAVE10 redemptions -100%",
         "since": "08:30 UTC"},
        ["08:31:12 INFO checkout ok order=60101 coupon=SAVE10 discount_percent=0",
         "08:33:40 INFO checkout ok order=60107 coupon=OLD5 discount_percent=5",
         "08:35:02 WARN support ticket #5530: 'SAVE10 code not working'"],
        "orders/coupons.py", "if now > coupon[\"expires\"]:", "if now < coupon[\"expires\"]:",
        "coupons: fix expiry comparison", severity="high",
        hidden_test="""
from datetime import datetime, timezone
from orders.coupons import coupon_percent
def test_hidden():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert coupon_percent("SAVE10", now) == 10
    assert coupon_percent("OLD5", now) == 0
    assert coupon_percent(None, now) == 0
"""),
    Incident(
        "INC-106", "500 errors on checkout without a coupon", "bug",
        {"name": "checkout_5xx_rate_high", "service": "orders", "value": "61%", "threshold": "0.5%",
         "since": "13:05 UTC"},
        ["13:05:22 ERROR checkout 500 order=71002",
         "Traceback (most recent call last):",
         '  File "orders/api.py", line 23, in checkout',
         "KeyError: 'coupon'",
         "13:05:40 INFO checkout ok order=71003 coupon=SAVE10"],
        "orders/api.py", 'coupon_percent(request.get("coupon"))', 'coupon_percent(request["coupon"])',
        "api: read coupon directly", severity="high",
        hidden_test="""
from orders.api import checkout
def test_hidden():
    status, body = checkout({"items": [{"sku": "A", "price_cents": 1000, "qty": 1}]}, {"A": 1}, lambda t: True)
    assert status == 200 and body["total_cents"] == 1080
    status, body = checkout({"items": [{"sku": "A", "price_cents": 1000, "qty": 1}], "coupon": "SAVE10"},
                            {"A": 1}, lambda t: True)
    assert body["total_cents"] == 972
"""),
    Incident(
        "INC-107", "Receipts show wrong amounts", "bug",
        {"name": "receipt_complaints", "service": "orders", "value": "37 tickets in 2h", "since": "10:00 UTC"},
        ["10:12:01 WARN support ticket #5601: 'charged $5.05 but receipt says $5.5'",
         "10:20:44 WARN support ticket #5603: 'receipt says $12.7, card shows $12.07'",
         "10:21:10 INFO checkout ok order=81022 total_cents=1207 total=$12.7"],
        "orders/money.py", "{cents % 100:02d}", "{cents % 100}",
        "money: simplify format string", severity="low",
        hidden_test="""
from orders.money import format_cents
def test_hidden():
    assert format_cents(505) == "$5.05"
    assert format_cents(1207) == "$12.07"
    assert format_cents(-199) == "-$1.99"
    assert format_cents(0) == "$0.00"
"""),
    Incident(
        "INC-108", "Inventory drifting negative after declined payments", "bug",
        {"name": "inventory_negative_stock", "service": "orders", "value": "212 SKUs below zero",
         "since": "07:00 UTC"},
        ["07:01:15 INFO checkout 402 order=55010 sku=SKU-3 qty=2 stock_before=10 stock_after=6",
         "07:02:40 INFO checkout 402 order=55014 sku=SKU-9 qty=1 stock_before=1 stock_after=-1",
         "07:05:00 WARN inventory-audit SKU-9 count=-1"],
        "orders/inventory.py", "stock.get(sku, 0) + qty", "stock.get(sku, 0) - qty",
        "inventory: tidy release()", severity="high",
        hidden_test="""
from orders.api import checkout
def test_hidden():
    stock = {"A": 5}
    status, _ = checkout({"items": [{"sku": "A", "price_cents": 100, "qty": 2}]}, stock, lambda t: False)
    assert status == 402 and stock["A"] == 5
"""),
    Incident(
        "INC-109", "Health check latency spike", "noise",
        {"name": "healthcheck_latency_high", "service": "orders", "value": "1.9s", "threshold": "1.5s",
         "since": "03:00 UTC", "duration": "4 minutes, resolved"},
        ["03:00:00 INFO deploy started version=4.18.2 strategy=rolling",
         "03:00:40 INFO healthcheck slow instance=orders-3 (warming up after deploy)",
         "03:03:55 INFO deploy finished; all instances healthy",
         "03:04:00 INFO checkout error rate 0.02% (normal)"],
        severity="low"),
    Incident(
        "INC-110", "Disk usage high on log volume", "noise",
        {"name": "disk_usage_high", "service": "orders-host-2", "value": "91%", "threshold": "90%",
         "mount": "/var/log"},
        ["04:10:00 INFO logrotate last ran 6 days ago (cron disabled during migration)",
         "04:10:00 INFO checkout error rate 0.01% (normal), latency p99 180ms (normal)"],
        severity="low"),
]

BY_ID = {i.id: i for i in INCIDENTS}
