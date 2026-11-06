"""Small, defensive conversions for values loaded from QSettings."""

from __future__ import annotations

from typing import Any


def optional_positive_float(value: Any) -> float | None:
    """Return a positive float, treating blank/invalid settings as automatic."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
