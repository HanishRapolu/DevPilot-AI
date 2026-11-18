"""Intentionally faulty targets for later DevPilot investigations. Do not fix in Phase 1."""


def discounted_price(price: float, discount_percent: float) -> float:
    """Return a nonnegative price after a percentage discount (0 through 100)."""
    if price < 0 or not 0 <= discount_percent <= 100:
        raise ValueError("Invalid price or discount")
    return round(price * (1 - discount_percent / 100), 2)


def average(values: list[float]) -> float:
    """Return the arithmetic mean; an empty input raises ValueError."""
    if not values:
        raise ValueError("At least one value is required")
    return sum(values) / len(values)
