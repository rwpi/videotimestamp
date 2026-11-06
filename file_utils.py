"""Small file and naming helpers shared by the workflow modules."""

from __future__ import annotations

import datetime
import re
from pathlib import Path


def natural_sort_key(value: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def parse_clip_datetime(value: str, preferred_order: str | None = None) -> datetime.datetime | None:
    try:
        date_part, _ = value.split("_", 1)
        a_str, b_str, _ = date_part.split("-", 2)
        a_is_alpha = a_str.isalpha()
        b_is_alpha = b_str.isalpha()
        if not a_is_alpha:
            a = int(a_str)
        else:
            a = None
        if not b_is_alpha:
            b = int(b_str)
        else:
            b = None
    except ValueError:
        a = b = None
        a_is_alpha = b_is_alpha = False

    formats = []
    if a_is_alpha and not b_is_alpha:
        formats.append("%b-%d-%Y_%H-%M-%S")
    elif b_is_alpha and not a_is_alpha:
        formats.append("%d-%b-%Y_%H-%M-%S")
    elif a is not None and b is not None:
        if a > 12 and b <= 12:
            formats.append("%d-%m-%Y_%H-%M-%S")
        elif b > 12 and a <= 12:
            formats.append("%m-%d-%Y_%H-%M-%S")
        elif preferred_order == "DMY":
            formats.append("%d-%m-%Y_%H-%M-%S")
        elif preferred_order == "MDY":
            formats.append("%m-%d-%Y_%H-%M-%S")

    fallback_formats = [
        "%m-%d-%Y_%H-%M-%S",
        "%d-%m-%Y_%H-%M-%S",
        "%b-%d-%Y_%H-%M-%S",
        "%d-%b-%Y_%H-%M-%S",
    ]
    if not formats:
        formats = fallback_formats
    else:
        for fmt in fallback_formats:
            if fmt not in formats:
                formats.append(fmt)

    for fmt in formats:
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def unique_output_path(folder: Path, name: str) -> Path:
    """A free path named ``name`` inside ``folder``, suffixing on collision."""
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while True:
        candidate = folder / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
