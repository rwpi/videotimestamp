"""Timestamp must keep both clips when two share an embedded second.

Body cams started together write clips whose embedded recording time is the
same second. Import already keeps both originals in one date folder;
timestamp used to derive one output name from that second, stamp the
first clip to it, and then skip the second as ``output_exists`` even though a
different clip owned the name.
"""

from pathlib import Path

from timestamp import Worker


def _worker(root: Path) -> Worker:
    return Worker([], str(root), None, False, False, False, False, "%m-%d-%Y")


def _stub_processing(worker: Worker, monkeypatch) -> None:
    monkeypatch.setattr("timestamp.replacement_blocked_reason", lambda path: None)
    worker.get_camera_identity = lambda file_path: ""
    worker.get_metadata_timestamp = lambda file_path, camera_identity=None: (
        "2026:11:05 14:30:00",
        None,
    )
    worker.get_video_duration_seconds = lambda file_path: 10.0
    worker.should_skip_timestamp_overlay = lambda file_path, camera_identity: False

    def fake_burn(file_path, start_time_unix, output_file, progress_callback):
        Path(output_file).write_bytes(f"stamped {Path(file_path).name}".encode())
        return True

    worker.burn_timestamp = fake_burn
    worker.validate_processed_output = lambda output_file, duration: True


def _run(worker: Worker, files) -> tuple[list[str], list[str], list[str]]:
    processed, skipped, outputs = [], [], []
    worker.fileProcessed.connect(processed.append)
    worker.fileSkipped.connect(skipped.append)
    worker.outputCreated.connect(outputs.append)
    worker.files = list(files)
    worker.process_videos(worker.files, lambda value: None)
    return processed, skipped, outputs


def test_second_clip_in_the_same_second_is_stamped_under_a_unique_name(
    tmp_path, monkeypatch
):
    first = tmp_path / "CLIP0001.mp4"
    second = tmp_path / "CLIP0001_1.mp4"
    first.write_bytes(b"first clip bytes")
    second.write_bytes(b"second clip bytes")

    worker = _worker(tmp_path)
    _stub_processing(worker, monkeypatch)

    processed, skipped, outputs = _run(worker, [str(first), str(second)])

    assert outputs == [
        str(tmp_path / "11-05-2026_14-30-00.mp4"),
        str(tmp_path / "11-05-2026_14-30-00_1.mp4"),
    ]
    assert processed == [str(first), str(second)]
    assert skipped == []
    assert worker.skipped_reasons == {}
    # Each stamped output carries its own clip, not the other clip's bytes.
    assert (tmp_path / "11-05-2026_14-30-00.mp4").read_bytes() == (
        b"stamped CLIP0001.mp4"
    )
    assert (tmp_path / "11-05-2026_14-30-00_1.mp4").read_bytes() == (
        b"stamped CLIP0001_1.mp4"
    )
    # Default retain_originals: both originals are archived, neither deleted.
    originals = tmp_path / "originals"
    assert (originals / "CLIP0001.mp4").read_bytes() == b"first clip bytes"
    assert (originals / "CLIP0001_1.mp4").read_bytes() == b"second clip bytes"


def test_rerun_keeps_each_stamped_clip_on_its_own_name(tmp_path, monkeypatch):
    """A no-op re-run must not stack ``_1_1`` names on already-stamped clips."""
    first = tmp_path / "CLIP0001.mp4"
    second = tmp_path / "CLIP0001_1.mp4"
    first.write_bytes(b"first clip bytes")
    second.write_bytes(b"second clip bytes")

    first_worker = _worker(tmp_path)
    _stub_processing(first_worker, monkeypatch)
    _run(first_worker, [str(first), str(second)])

    stamped = sorted(str(path) for path in tmp_path.glob("*.mp4"))
    assert [Path(path).name for path in stamped] == [
        "11-05-2026_14-30-00.mp4",
        "11-05-2026_14-30-00_1.mp4",
    ]

    rerun_worker = _worker(tmp_path)
    _stub_processing(rerun_worker, monkeypatch)
    processed, skipped, outputs = _run(rerun_worker, stamped)

    assert [Path(path).name for path in outputs] == [
        "11-05-2026_14-30-00.mp4",
        "11-05-2026_14-30-00_1.mp4",
    ]
    assert skipped == []
    assert rerun_worker.skipped_reasons == {}
    assert sorted(path.name for path in tmp_path.glob("*.mp4")) == [
        "11-05-2026_14-30-00.mp4",
        "11-05-2026_14-30-00_1.mp4",
    ]
    # Each file is stamped in place over itself, not over its neighbour.
    assert (tmp_path / "11-05-2026_14-30-00.mp4").read_bytes() == (
        b"stamped 11-05-2026_14-30-00.mp4"
    )
    assert (tmp_path / "11-05-2026_14-30-00_1.mp4").read_bytes() == (
        b"stamped 11-05-2026_14-30-00_1.mp4"
    )
