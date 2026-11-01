def backoff_seconds(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Exponential backoff for calls to the payment provider, never above `cap`."""
    return min(cap, base * 2 ** attempt)
