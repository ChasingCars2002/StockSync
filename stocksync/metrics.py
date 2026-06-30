"""Parsing helpers for the raw string values Finviz returns.

Finviz reports everything as display strings: ``"1.23B"``, ``"45.6%"``,
``"-"`` for missing data, ``"12.34"`` for plain numbers and so on. The
functions here turn those into Python numbers so the rest of the codebase can
reason about them numerically.
"""

from __future__ import annotations

from typing import Optional

# Suffix multipliers used by Finviz for large numbers (market cap, volume...).
_SUFFIXES = {
    "K": 1_000,
    "M": 1_000_000,
    "B": 1_000_000_000,
    "T": 1_000_000_000_000,
}

# Values Finviz uses to mean "no data".
_EMPTY = {"", "-", "—", "n/a", "N/A", "null", "None"}


def is_missing(value: object) -> bool:
    """Return ``True`` when *value* represents missing/unavailable data."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() in _EMPTY:
        return True
    return False


def parse_number(value: object) -> Optional[float]:
    """Parse a Finviz numeric string into a ``float``.

    Handles magnitude suffixes (``K``/``M``/``B``/``T``), thousands
    separators, percent signs, surrounding whitespace and currency symbols.
    Returns ``None`` for missing values or anything unparseable.

    >>> parse_number("1.23B")
    1230000000.0
    >>> parse_number("45.6%")
    45.6
    >>> parse_number("-")
    """
    if is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    # Strip common decorations that are not part of the number itself.
    text = text.replace(",", "").replace("$", "").replace("%", "").strip()
    if not text:
        return None

    multiplier = 1.0
    if text[-1] in _SUFFIXES:
        multiplier = _SUFFIXES[text[-1]]
        text = text[:-1]

    try:
        return float(text) * multiplier
    except ValueError:
        return None


def parse_percent(value: object) -> Optional[float]:
    """Parse a percentage string (``"12.5%"``) into a float (``12.5``).

    This is a thin alias over :func:`parse_number` since Finviz percentages
    are already expressed in percent units; it exists to make call sites
    self-documenting.
    """
    return parse_number(value)


def humanize_number(value: Optional[float]) -> str:
    """Render a float back into a compact human string (inverse of parse).

    >>> humanize_number(1_230_000_000)
    '1.23B'
    """
    if value is None:
        return "-"
    abs_value = abs(value)
    for suffix, scale in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs_value >= scale:
            return f"{value / scale:.2f}{suffix}"
    return f"{value:.2f}"


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Constrain *value* to the inclusive ``[low, high]`` range."""
    return max(low, min(high, value))
