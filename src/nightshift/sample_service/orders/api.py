"""Checkout handler. Returns (status_code, body)."""
from .coupons import coupon_percent
from .inventory import OutOfStock, release, reserve
from .money import format_cents
from .pricing import order_total

TAX_RATE = 0.08


def checkout(request: dict, stock: dict[str, int], charge) -> tuple[int, dict]:
    items = request.get("items") or []
    if not items:
        return 400, {"error": "cart is empty"}
    reserved = []
    try:
        for item in items:
            reserve(stock, item["sku"], item["qty"])
            reserved.append(item)
    except OutOfStock as e:
        for item in reserved:
            release(stock, item["sku"], item["qty"])
        return 409, {"error": str(e)}
    total = order_total(items, coupon_percent(request.get("coupon")), TAX_RATE)
    if not charge(total):
        for item in reserved:
            release(stock, item["sku"], item["qty"])
        return 402, {"error": "payment declined"}
    return 200, {"total_cents": total, "total": format_cents(total)}
