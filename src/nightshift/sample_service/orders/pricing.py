"""Prices are integers in cents. Never use floats for money."""


def line_total(price_cents: int, qty: int) -> int:
    if qty < 0:
        raise ValueError("quantity cannot be negative")
    return price_cents * qty


def apply_discount(total_cents: int, percent: int) -> int:
    """Take `percent` percent off. 10 means 10%."""
    if not 0 <= percent <= 100:
        raise ValueError("discount must be between 0 and 100")
    return total_cents - total_cents * percent // 100


def add_tax(total_cents: int, rate: float) -> int:
    """Add sales tax, rounded to the nearest cent."""
    return total_cents + round(total_cents * rate)


def order_total(items: list[dict], discount_percent: int = 0, tax_rate: float = 0.0) -> int:
    subtotal = sum(line_total(i["price_cents"], i["qty"]) for i in items)
    return add_tax(apply_discount(subtotal, discount_percent), tax_rate)
