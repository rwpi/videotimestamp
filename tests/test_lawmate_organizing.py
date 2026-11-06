from __future__ import annotations

import datetime

import clip_utils


class _Settings:
    def __init__(self, *_args):
        pass

    def value(self, key, default=None, **_kwargs):
        values = {
            "date_format": "%m-%d-%Y",
            "manually_adjusted_for_dst": False,
            "add_hour": False,
            "subtract_hour": False,
        }
        return values.get(key, default)


def _isolate(monkeypatch, lawmate_paths):
    monkeypatch.setattr(clip_utils, "QSettings", _Settings)
    monkeypatch.setattr(clip_utils, "preferred_date_order_from_settings", lambda: "MDY")
    monkeypatch.setattr(
        clip_utils,
        "get_lawmate_exif_datetime",
        lambda path: lawmate_paths.get(path),
    )
    monkeypatch.setattr(clip_utils, "is_lawmate_file", lambda path: path in lawmate_paths)


def test_lawmate_is_normalized_from_metadata_before_clip_numbering(monkeypatch, tmp_path):
    earlier = tmp_path / "08-28-2026_09-30-00.MOV"
    lawmate = tmp_path / "RECO0005.MOV"
    earlier.write_bytes(b"ordinary clip")
    lawmate.write_bytes(b"lawmate clip")
    _isolate(monkeypatch, {lawmate: datetime.datetime(2026, 8, 28, 9, 36, 58)})

    clip_utils.organize_clips([earlier, lawmate], use_clip_numbers=True, log=lambda _text: None)

    earlier_output = tmp_path / "CLIP1_08-28-2026_09-30-00.MOV"
    lawmate_output = tmp_path / "CLIP2_08-28-2026_09-36-58.MOV"
    assert earlier_output.read_bytes() == b"ordinary clip"
    assert lawmate_output.read_bytes() == b"lawmate clip"
    assert not lawmate.exists()
    assert not list(tmp_path.glob("*COVERT*"))


def test_numbering_can_be_turned_off(monkeypatch, tmp_path):
    clip = tmp_path / "08-28-2026_09-30-00.mp4"
    clip.write_bytes(b"clip")
    _isolate(monkeypatch, {})

    clip_utils.organize_clips([clip], use_clip_numbers=False, log=lambda _text: None)

    assert clip.exists()


def test_filename_tags_survive_numbering(monkeypatch, tmp_path):
    clip = tmp_path / "08-28-2026_09-30-00_SUBJECT.mp4"
    clip.write_bytes(b"clip")
    _isolate(monkeypatch, {})

    clip_utils.organize_clips([clip], use_clip_numbers=True, log=lambda _text: None)

    assert (tmp_path / "CLIP1_08-28-2026_09-30-00_SUBJECT.mp4").exists()


def test_raw_clips_that_are_not_lawmate_are_left_alone(monkeypatch, tmp_path):
    raw = tmp_path / "IMG_0001.mov"
    raw.write_bytes(b"clip")
    _isolate(monkeypatch, {})
    lines = []

    clip_utils.organize_clips([raw], use_clip_numbers=True, log=lines.append)

    assert raw.exists()
    assert any("non-LawMate" in line for line in lines)
