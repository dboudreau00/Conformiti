"""Counts in notification copy."""


def count_of(n, singular, plural=None):
    """``n`` with its noun agreeing: "1 day", "30 days", "0 questions"."""
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"
