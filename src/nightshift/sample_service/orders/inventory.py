class OutOfStock(Exception):
    pass


def reserve(stock: dict[str, int], sku: str, qty: int) -> None:
    """Take `qty` units of `sku` out of stock, or raise OutOfStock."""
    available = stock.get(sku, 0)
    if qty > available:
        raise OutOfStock(f"{sku}: wanted {qty}, have {available}")
    stock[sku] = available - qty


def release(stock: dict[str, int], sku: str, qty: int) -> None:
    """Put units back, for example when a payment fails."""
    stock[sku] = stock.get(sku, 0) + qty
