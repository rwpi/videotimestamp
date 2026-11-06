from __future__ import annotations

import pytest

from classification_tags import classification_from_filename


@pytest.mark.parametrize(
    "name, expected",
    [
        ("08-28-2026_09-30-00.mp4", None),
        ("CLIP3_08-28-2026_09-30-00_SUBJECT.mp4", "SUBJECT"),
        ("08-28-2026_09-30-00_integrity.mp4", "INTEGRITY"),
        ("08-28-2026_09-30-00_PERSON_SUBJECT.mp4", "SUBJECT"),
    ],
)
def test_classification_comes_from_the_filename(name, expected):
    assert classification_from_filename(f"/footage/{name}") == expected
