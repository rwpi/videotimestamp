"""Clip timestamps follow the day-first / month-first choice in the date setting."""

from __future__ import annotations

import pytest

import date_settings
import clip_utils


class _Setting:
    def __init__(self, date_format):
        self._date_format = date_format

    def value(self, key, default=None, **_kwargs):
        assert key == "date_format"
        return self._date_format


@pytest.mark.parametrize(
    "date_format, expected_order",
    [
        ("%d-%m-%Y", "DMY"),
        ("%d/%m/%Y", "DMY"),
        ("%m-%d-%Y", "MDY"),
        ("%b-%d-%Y", "MDY"),
        ("%Y-%m-%d", None),
        ("", None),
    ],
)
def test_date_order_reader_returns_only_the_values_parsing_expects(
    monkeypatch, date_format, expected_order
):
    # file_utils.parse_clip_datetime compares against uppercase "DMY"/"MDY";
    # any other spelling silently falls through to month-first.
    monkeypatch.setattr(date_settings, "QSettings", lambda *args: _Setting(date_format))

    assert date_settings.preferred_date_order_from_settings() == expected_order


def test_clip_order_honours_day_first_date_setting(monkeypatch, tmp_path):
    # Under DMY the second file is 11 October and the first is 10 November, so
    # the October clip numbers first. Month-first reads them the other way
    # round and would put the November clip first.
    november_clip = tmp_path / "CLIP5_10-11-2026_10-00-00_A.mp4"
    october_clip = tmp_path / "CLIP9_11-10-2026_10-00-00_B.mp4"
    november_clip.write_bytes(b"a")
    october_clip.write_bytes(b"b")
    monkeypatch.setattr(clip_utils, "preferred_date_order_from_settings", lambda: "DMY")
    log: list[str] = []

    clip_utils.cliporder_rename_files(
        [november_clip, october_clip], dry_run=True, log=log.append
    )

    destinations = [line.rsplit(" -> ", 1)[1] for line in log]
    assert destinations == [
        "CLIP1_11-10-2026_10-00-00_B.mp4",
        "CLIP2_10-11-2026_10-00-00_A.mp4",
    ]
