from __future__ import annotations

import re
from pathlib import Path


_TRAILING_EXTRACTABLE_TAGS = re.compile(
    r"(_(INTEGRITY|CLAIMANT|HUMAN|UNKNOWN|CAR|PERSON|SUBJECT))+$",
    flags=re.IGNORECASE,
)


def extract_trailing_tags(stem: str) -> str:
    match = _TRAILING_EXTRACTABLE_TAGS.search(stem)
    return match.group(1) if match else ""


SUBJECT_CLASSIFICATIONS = ("CLAIMANT", "SUBJECT", "HUMAN")


def classification_from_filename(path: Path | str) -> str | None:
    """Read the trailing `_SUBJECT` / `_INTEGRITY` / ... tag from a clip name."""
    tag = extract_trailing_tags(Path(path).stem)
    if not tag:
        return None
    # A stem may carry several stacked tags; the last one is the current one.
    return tag.strip("_").split("_")[-1].upper() or None
