from __future__ import annotations

import datetime
from pathlib import Path

import pytest

import importtoday

TARGET_DATE = datetime.date(2026, 8, 14)
DATE_LABEL = "08-14-2026"


class _FakeSettings:
    """In-memory QSettings stand-in; ``importtoday`` imported QSettings directly."""

    store: dict[str, object] = {}

    def __init__(self, *_args, **_kwargs):
        pass

    def value(self, key, default=None, type=None):  # noqa: A002 - QSettings signature
        return self.store.get(key, default)

    def setValue(self, key, value):
        self.store[key] = value


@pytest.fixture(autouse=True)
def _reset_settings():
    _FakeSettings.store = {}
    yield
    _FakeSettings.store = {}


def _mount_only(monkeypatch, cards):
    """Stand in for ``Path('/Volumes').iterdir()`` so no real cards are scanned."""
    real_iterdir = Path.iterdir

    def fake_iterdir(self):
        if str(self) == "/Volumes":
            return iter(cards)
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)


def _run_import(monkeypatch, destination_base, recording_times):
    monkeypatch.setattr(importtoday, "QSettings", _FakeSettings)
    monkeypatch.setattr(
        importtoday,
        "read_embedded_recording_datetime",
        lambda path: recording_times.get(path),
    )
    thread = importtoday.ImportThread(
        selected_date=TARGET_DATE,
        destination_base=str(destination_base),
    )
    finished: list[tuple[str, list[str]]] = []
    errors: list[str] = []
    thread.finished.connect(lambda folder, files: finished.append((folder, list(files))))
    thread.error.connect(errors.append)
    thread.run()
    assert errors == []
    assert len(finished) == 1
    return finished[0]


def _make_clip(card: Path, payload: bytes) -> Path:
    clip = card / "DCIM" / "100MEDIA" / "CLIP0001.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(payload)
    return clip


def _ledger_values():
    return {
        key: value
        for key, value in _FakeSettings.store.items()
        if str(key).startswith("import_ledger/")
    }


def test_two_cards_sharing_a_clip_basename_are_both_imported(tmp_path, monkeypatch):
    """A second card's CLIP0001.mp4 must not vanish behind the first card's.

    Both cards are mounted in one run and hold an identically named clip from
    a different recording time. The first copy owns the plain destination name;
    the second must land under a unique name instead of being skipped while the
    ledger still records it as imported.
    """
    card_a = tmp_path / "CARD_A"
    card_b = tmp_path / "CARD_B"
    clip_a = _make_clip(card_a, b"card-a-clip-bytes")
    clip_b = _make_clip(card_b, b"card-b-clip-bytes-differ")
    _mount_only(monkeypatch, [card_a, card_b])

    folder, files = _run_import(
        monkeypatch,
        tmp_path / "movies",
        {
            clip_a: datetime.datetime(2026, 8, 14, 9, 0, 0),
            clip_b: datetime.datetime(2026, 8, 14, 9, 30, 0),
        },
    )

    folder_path = Path(folder)
    assert folder_path == tmp_path / "movies" / DATE_LABEL
    assert sorted(Path(path).name for path in files) == [
        "CLIP0001.mp4",
        "CLIP0001_1.mp4",
    ]
    assert all(Path(path).exists() for path in files)
    imported = {path.name: path.read_bytes() for path in folder_path.glob("*.mp4")}
    assert imported == {
        "CLIP0001.mp4": b"card-a-clip-bytes",
        "CLIP0001_1.mp4": b"card-b-clip-bytes-differ",
    }

    # The ledger must record both imports, and only files that are on disk.
    ledgers = _ledger_values()
    assert len(ledgers) == 1
    entries = list(next(iter(ledgers.values())))
    assert len(entries) == 2
    assert all("|CLIP0001.mp4" in entry for entry in entries)

    # A re-run is a no-op: nothing is copied again and no duplicate appears.
    folder_again, files_again = _run_import(
        monkeypatch,
        tmp_path / "movies",
        {
            clip_a: datetime.datetime(2026, 8, 14, 9, 0, 0),
            clip_b: datetime.datetime(2026, 8, 14, 9, 30, 0),
        },
    )
    assert folder_again == folder
    assert files_again == []
    assert sorted(path.name for path in Path(folder).glob("*.mp4")) == [
        "CLIP0001.mp4",
        "CLIP0001_1.mp4",
    ]


def test_two_cards_with_the_same_fingerprint_are_both_imported(tmp_path, monkeypatch):
    """Same basename, timestamp and size are not proof of the same clip.

    Two body cams started together produce ``CLIP0001.mp4`` files with the same
    embedded time and, at the same bitrate, the same size. The fingerprint that
    guards re-imports cannot tell them apart, so the second must not be skipped
    as if it were this run's copy of the first.
    """
    card_a = tmp_path / "CARD_A"
    card_b = tmp_path / "CARD_B"
    clip_a = _make_clip(card_a, b"a" * 64)
    clip_b = _make_clip(card_b, b"b" * 64)
    _mount_only(monkeypatch, [card_a, card_b])
    same_time = datetime.datetime(2026, 8, 14, 9, 0, 0)

    folder, files = _run_import(
        monkeypatch,
        tmp_path / "movies",
        {clip_a: same_time, clip_b: same_time},
    )

    folder_path = Path(folder)
    assert sorted(Path(path).name for path in files) == [
        "CLIP0001.mp4",
        "CLIP0001_1.mp4",
    ]
    imported = {path.name: path.read_bytes() for path in folder_path.glob("*.mp4")}
    assert imported == {"CLIP0001.mp4": b"a" * 64, "CLIP0001_1.mp4": b"b" * 64}


def test_second_card_with_the_same_fingerprint_is_imported_in_a_later_run(tmp_path, monkeypatch):
    """The ledger cannot tell two same-named, same-time, same-size clips apart.

    ``test_two_cards_with_the_same_fingerprint_are_both_imported`` covers the
    two cards in one run. Imported in separate runs, the second card's
    fingerprint is already in the ledger from the first, so the clip must not
    be skipped on the ledger alone: the bytes decide. A different clip lands
    under a unique name; a re-import of either card stays a no-op.
    """
    card_a = tmp_path / "CARD_A"
    card_b = tmp_path / "CARD_B"
    clip_a = _make_clip(card_a, b"a" * 64)
    clip_b = _make_clip(card_b, b"b" * 64)
    same_time = datetime.datetime(2026, 8, 14, 9, 0, 0)

    # Run 1: card A alone.
    _mount_only(monkeypatch, [card_a])
    folder, files = _run_import(
        monkeypatch,
        tmp_path / "movies",
        {clip_a: same_time},
    )
    folder_path = Path(folder)
    assert [Path(path).name for path in files] == ["CLIP0001.mp4"]

    # Run 2: card B alone, same name/time/size, different bytes.
    _mount_only(monkeypatch, [card_b])
    folder_again, files_again = _run_import(
        monkeypatch,
        tmp_path / "movies",
        {clip_b: same_time},
    )
    assert folder_again == folder
    assert [Path(path).name for path in files_again] == ["CLIP0001_1.mp4"]
    imported = {path.name: path.read_bytes() for path in folder_path.glob("*.mp4")}
    assert imported == {"CLIP0001.mp4": b"a" * 64, "CLIP0001_1.mp4": b"b" * 64}

    # Re-importing either card stays a no-op: nothing is copied again and no
    # duplicate appears, even for the card whose copy carries the suffix.
    _mount_only(monkeypatch, [card_a])
    _, files_a = _run_import(monkeypatch, tmp_path / "movies", {clip_a: same_time})
    assert files_a == []
    _mount_only(monkeypatch, [card_b])
    _, files_b = _run_import(monkeypatch, tmp_path / "movies", {clip_b: same_time})
    assert files_b == []
    assert sorted(path.name for path in folder_path.glob("*.mp4")) == [
        "CLIP0001.mp4",
        "CLIP0001_1.mp4",
    ]
    assert {path.name: path.read_bytes() for path in folder_path.glob("*.mp4")} == imported


def test_reimport_after_timestamping_renamed_the_copy_is_a_noop(tmp_path, monkeypatch):
    """Once timestamping renames the copy, a re-import must stay a no-op.

    With the earlier copy renamed away from the basename, a re-import of the
    same card and a different card are indistinguishable, so the ledger hit
    keeps today's skip instead of guessing.
    """
    card_a = tmp_path / "CARD_A"
    card_b = tmp_path / "CARD_B"
    clip_a = _make_clip(card_a, b"a" * 64)
    clip_b = _make_clip(card_b, b"b" * 64)
    same_time = datetime.datetime(2026, 8, 14, 9, 0, 0)

    _mount_only(monkeypatch, [card_a])
    folder, files = _run_import(
        monkeypatch,
        tmp_path / "movies",
        {clip_a: same_time},
    )
    assert [Path(path).name for path in files] == ["CLIP0001.mp4"]

    # Timestamping renames the stamped copy and retires the basename.
    folder_path = Path(folder)
    (folder_path / "CLIP0001.mp4").rename(folder_path / "08-14-2026_09-00-00.mp4")

    _mount_only(monkeypatch, [card_a])
    _, files_a = _run_import(monkeypatch, tmp_path / "movies", {clip_a: same_time})
    assert files_a == []
    _mount_only(monkeypatch, [card_b])
    _, files_b = _run_import(monkeypatch, tmp_path / "movies", {clip_b: same_time})
    assert files_b == []
    assert sorted(path.name for path in folder_path.glob("*.mp4")) == [
        "08-14-2026_09-00-00.mp4"
    ]


def test_existing_identical_copy_is_not_recopied_when_the_ledger_is_gone(tmp_path, monkeypatch):
    """A lost ledger must not turn a re-import into ``CLIP0001_1.mp4`` noise."""
    card = tmp_path / "CARD"
    clip = _make_clip(card, b"same-source-bytes")
    folder_path = tmp_path / "movies" / DATE_LABEL
    folder_path.mkdir(parents=True)
    (folder_path / "CLIP0001.mp4").write_bytes(b"same-source-bytes")
    _mount_only(monkeypatch, [card])

    folder, files = _run_import(
        monkeypatch,
        tmp_path / "movies",
        {clip: datetime.datetime(2026, 8, 14, 9, 0, 0)},
    )

    assert folder == str(folder_path)
    assert [Path(path).name for path in files] == ["CLIP0001.mp4"]
    assert sorted(path.name for path in folder_path.glob("*.mp4")) == ["CLIP0001.mp4"]
    assert len(next(iter(_ledger_values().values()))) == 1


def test_different_source_from_an_earlier_run_gets_a_unique_name(tmp_path, monkeypatch):
    """Card B imported later, for the same date, must still copy its clip."""
    card_b = tmp_path / "CARD_B"
    clip_b = _make_clip(card_b, b"card-b-bytes")
    folder_path = tmp_path / "movies" / DATE_LABEL
    folder_path.mkdir(parents=True)
    (folder_path / "CLIP0001.mp4").write_bytes(b"card-a-bytes-from-earlier-run")
    _mount_only(monkeypatch, [card_b])

    folder, files = _run_import(
        monkeypatch,
        tmp_path / "movies",
        {clip_b: datetime.datetime(2026, 8, 14, 9, 30, 0)},
    )

    assert folder == str(folder_path)
    assert [Path(path).name for path in files] == ["CLIP0001_1.mp4"]
    assert (folder_path / "CLIP0001.mp4").read_bytes() == b"card-a-bytes-from-earlier-run"
    assert (folder_path / "CLIP0001_1.mp4").read_bytes() == b"card-b-bytes"


def test_import_refuses_a_destination_on_a_camera_card(tmp_path, monkeypatch):
    """The dated folder must never be created on a card.

    A card holds the only copy of its footage. Importing to a folder on it
    would write the dated folder there, so the run must fail before mkdir.
    The volume is faked the same way as the card-guard tests: a removable
    volume carrying PRIVATE, which is never touched on disk.
    """
    import original_archive

    card = Path("/Volumes/TESTCARD")
    destination = card / "Footage"
    real_is_dir = Path.is_dir

    def fake_is_dir(self):
        return str(self) == str(card / "PRIVATE") or real_is_dir(self)

    original_archive._volume_is_removable.cache_clear()
    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    monkeypatch.setattr(
        original_archive, "_volume_is_removable", lambda _root: True
    )
    monkeypatch.setattr(importtoday, "QSettings", _FakeSettings)

    thread = importtoday.ImportThread(
        selected_date=TARGET_DATE,
        destination_base=str(destination),
    )
    finished: list[tuple[str, list[str]]] = []
    errors: list[str] = []
    thread.finished.connect(lambda folder, files: finished.append((folder, list(files))))
    thread.error.connect(errors.append)
    thread.run()

    assert finished == []
    assert len(errors) == 1
    assert "VTS only ever copies from a card" in errors[0]
    assert not destination.exists()
    assert not (destination / DATE_LABEL).exists()
