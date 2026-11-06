"""A clip with no embedded timezone must keep its wall-clock time.

``Worker.to_unix_timestamp`` used to attach ``now().astimezone().tzinfo``, a
fixed offset for *today*, to a naive metadata time. ``fromtimestamp`` then
rendered the epoch with the zone rule that was in force on the clip's date, so
a summer clip processed in winter (or the reverse) came out an hour late and
the burned timestamp disagreed with the filename.

The bug only appears where the local zone observes DST, so these tests pin the
machine zone to America/Chicago rather than depending on the host's setting.
"""

import datetime
import os
import time

import pytest

from timestamp import Worker


def _worker(root) -> Worker:
    return Worker(
        [],
        str(root),
        None,
        False,
        False,
        False,
        False,
        "%m-%d-%Y",
    )


@pytest.fixture
def chicago_zone():
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset() is needed to simulate a local zone")
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "America/Chicago"
    time.tzset()
    # If the host has no zoneinfo database, tzset() silently falls back to UTC
    # and the assertions below would test nothing.
    if datetime.datetime(2026, 8, 14, 12, 0).astimezone().utcoffset() != datetime.timedelta(
        hours=-5
    ):
        _restore_zone(previous)
        pytest.skip("America/Chicago zone data is unavailable on this host")
    try:
        yield
    finally:
        _restore_zone(previous)


def _restore_zone(previous):
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    time.tzset()


def test_naive_metadata_time_uses_the_zone_rule_for_its_own_date(
    tmp_path, chicago_zone
):
    """Both seasons are asserted so this fails before the fix all year round.

    With today's fixed offset attached, whichever season is *not* the current
    one lands an hour off: processing in winter pushed August to 11:00, and
    processing in summer pulled November to 09:00.
    """
    worker = _worker(tmp_path)

    summer = worker.to_unix_timestamp("2026:08:14 10:00:00")
    winter = worker.to_unix_timestamp("2026:11:05 10:00:00")

    # 2026-08-14 10:00 CDT is 15:00 UTC; 2026-11-05 10:00 CST is 16:00 UTC.
    assert summer == 1786719600
    assert winter == 1793894400

    for epoch, expected in ((summer, (8, 14, 10)), (winter, (11, 5, 10))):
        rendered = datetime.datetime.fromtimestamp(epoch)
        assert (rendered.month, rendered.day, rendered.hour) == expected


def test_embedded_offset_still_wins_over_the_local_zone(tmp_path, chicago_zone):
    """The explicit-offset branches are correct and must stay that way."""
    worker = _worker(tmp_path)

    # Written into the timestamp (%z) and supplied by exiftool -TimeZone.
    assert worker.to_unix_timestamp("2026:08:14 10:00:00-06:00") == 1786723200
    assert (
        worker.to_unix_timestamp("2026:08:14 10:00:00", tz_offset="-06:00")
        == 1786723200
    )
