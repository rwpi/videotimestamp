"""Trim publishing preserves originals, names, and protected source locations."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

import original_archive
import video_trimmer_gui as trim
from workflow_schemas import validate_workflow_options


def _run_trim(source, *, start=0, mode=None):
    """Publish one trim through the real worker path; only the encoder is stubbed."""
    options = validate_workflow_options("trim", {})
    worker = trim.TrimWorker(
        source,
        start,
        start + 2,
        options["output_mode"] if mode is None else mode,
        use_hwaccel=False,
        remove_audio=True,
    )
    return worker._trim_video()


@pytest.fixture
def stub_encoder(monkeypatch):
    """Exercise the publishing path without depending on a video encoder."""
    monkeypatch.setattr(trim, "filter_hwaccel_methods", lambda: None)
    monkeypatch.setattr(trim.TrimWorker, "_has_audio_stream", lambda self: False)

    class SuccessfulEncoder:
        def __init__(self, command, **_kwargs):
            Path(command[-1]).write_bytes(b"trimmed clip")
            self.stdout = io.StringIO("progress=end\n")

        def wait(self):
            return 0

    monkeypatch.setattr(trim.subprocess, "Popen", SuccessfulEncoder)


@pytest.fixture
def encode_trim(stub_encoder, monkeypatch):
    """Month-first settings, as date_settings reports for a %m/%b date format."""
    monkeypatch.setattr(trim, "date_format_from_settings", lambda: "%m-%d-%Y")
    monkeypatch.setattr(trim, "preferred_date_order_from_settings", lambda: "MDY")
    return _run_trim


@pytest.fixture
def encode_trim_day_first(stub_encoder, monkeypatch):
    """Day-first settings, as date_settings reports for a %d date format."""
    monkeypatch.setattr(trim, "date_format_from_settings", lambda: "%d-%m-%Y")
    monkeypatch.setattr(trim, "preferred_date_order_from_settings", lambda: "DMY")
    return _run_trim


def test_default_trim_replaces_working_clip_and_archives_original(tmp_path, encode_trim):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"untrimmed original")

    output = encode_trim(source)

    assert output == source
    assert source.read_bytes() == b"trimmed clip"
    assert (tmp_path / "originals" / source.name).read_bytes() == b"untrimmed original"
    assert not (tmp_path / "trimmed_clips").exists()


def test_trim_replacement_adjusts_timestamp_and_preserves_clip_tags(tmp_path, encode_trim):
    source = tmp_path / "CLIP12_10-11-2026_23-59-59_SUBJECT.mp4"
    source.write_bytes(b"untrimmed original")

    output = encode_trim(source, start=2)

    assert output == tmp_path / "CLIP12_10-12-2026_00-00-01_SUBJECT.mp4"
    assert output.read_bytes() == b"trimmed clip"
    assert not source.exists()
    assert (tmp_path / "originals" / source.name).read_bytes() == b"untrimmed original"
    assert sorted(path.name for path in tmp_path.glob("*.mp4")) == [output.name]


def test_trim_replacement_honours_day_first_date_setting(tmp_path, encode_trim_day_first):
    # 10-11-2026 is 10 November to a day-first user, so the two-second trim
    # crosses midnight into 11 November. Reading it month-first would instead
    # land on 11 October and rename the clip to 12 October.
    source = tmp_path / "CLIP12_10-11-2026_23-59-59_SUBJECT.mp4"
    source.write_bytes(b"untrimmed original")

    output = encode_trim_day_first(source, start=2)

    assert output == tmp_path / "CLIP12_11-11-2026_00-00-01_SUBJECT.mp4"
    assert output.read_bytes() == b"trimmed clip"
    assert not source.exists()
    assert (tmp_path / "originals" / source.name).read_bytes() == b"untrimmed original"


def test_trim_preserves_existing_archive_and_timestamp_name_collision(tmp_path, encode_trim):
    source = tmp_path / "10-11-2026_12-00-00_PERSON.mp4"
    source.write_bytes(b"current untrimmed original")
    prior_archive = tmp_path / "originals" / source.name
    prior_archive.parent.mkdir()
    prior_archive.write_bytes(b"previous untrimmed original")
    collision = tmp_path / "10-11-2026_12-00-02_PERSON.mp4"
    collision.write_bytes(b"different working clip")

    output = encode_trim(source, start=2)

    assert output == collision.with_stem(collision.stem + "_1")
    assert output.read_bytes() == b"trimmed clip"
    assert collision.read_bytes() == b"different working clip"
    assert prior_archive.read_bytes() == b"previous untrimmed original"
    assert prior_archive.with_stem(source.stem + "_1").read_bytes() == b"current untrimmed original"


def test_explicit_dedicated_folder_choice_keeps_original_in_place(tmp_path, encode_trim):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"untrimmed original")

    output = encode_trim(source, mode="dedicated_folder")

    assert output == tmp_path / "trimmed_clips" / source.name
    assert output.read_bytes() == b"trimmed clip"
    assert source.read_bytes() == b"untrimmed original"
    assert not (tmp_path / "originals").exists()


def test_camera_card_guard_refuses_trim_instead_of_writing_beside_source(
    tmp_path, monkeypatch, encode_trim
):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"camera original")
    # A synthetic working folder stands in for a card; no /Volumes footage is
    # opened or changed by this regression check.
    monkeypatch.setattr(original_archive, "is_camera_card_path", lambda path: Path(path) == source)
    monkeypatch.setattr(trim, "is_camera_card_path", lambda path: Path(path) == source)

    with pytest.raises(RuntimeError, match="camera card"):
        encode_trim(source)

    # No output folder and no temporary file may appear on the card: the
    # encoder never starts, so the only copy of the footage is untouched.
    assert not (tmp_path / "trimmed_clips").exists()
    assert not (tmp_path / "originals").exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == [source.name]
    assert source.read_bytes() == b"camera original"
