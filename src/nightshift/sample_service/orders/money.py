def format_cents(cents: int) -> str:
    """1234 -> '$12.34'"""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
