from datetime import datetime, timezone

COUPONS = {
    "SAVE10": {"percent": 10, "expires": datetime(2030, 1, 1, tzinfo=timezone.utc)},
    "OLD5": {"percent": 5, "expires": datetime(2020, 1, 1, tzinfo=timezone.utc)},
}


def coupon_percent(code: str | None, now: datetime | None = None) -> int:
    """Discount percent for a coupon code. Unknown or expired codes give 0."""
    if not code:
        return 0
    coupon = COUPONS.get(code.upper())
    if coupon is None:
        return 0
    now = now or datetime.now(timezone.utc)
    if now > coupon["expires"]:
        return 0
    return coupon["percent"]
