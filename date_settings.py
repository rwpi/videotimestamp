"""Shared readers for the application's date-format settings."""
from __future__ import annotations

from PyQt5.QtCore import QSettings


def preferred_date_order_from_settings() -> str | None:
    """Which of day-first / month-first the user's date format implies."""
    settings = QSettings("VideoTimestamp", "VTS")
    fmt = settings.value("date_format", "%m-%d-%Y")
    if isinstance(fmt, str):
        if fmt.startswith("%d"):
            return "DMY"
        if fmt.startswith("%m") or fmt.startswith("%b"):
            return "MDY"
    return None
