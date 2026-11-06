from pathlib import Path

from timestamp import Worker


def _worker(root: Path) -> Worker:
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


def test_clip_without_embedded_date_is_reported_as_skipped(tmp_path):
    clip = tmp_path / "smoke.mp4"
    clip.write_bytes(b"synthetic clip with no metadata")

    worker = _worker(tmp_path)
    worker.files = [str(clip)]
    worker.get_camera_identity = lambda file_path: None
    worker.get_metadata_timestamp = lambda file_path, camera_identity=None: ("", None)

    statuses = []
    skipped = []
    worker.statusChanged.connect(statuses.append)
    worker.fileSkipped.connect(skipped.append)

    worker.process_videos(worker.files, lambda value: None)

    assert skipped == [str(clip)]
    # The job runner turns this reason into the sentence the Finder panel
    # shows when every clip was skipped.
    assert worker.skipped_reasons == {str(clip): "missing_date"}
    assert any(
        "smoke.mp4" in message and "no embedded recording date" in message
        for message in statuses
    )
    # The original is left in place and no output was invented.
    assert clip.read_bytes() == b"synthetic clip with no metadata"
    assert [path.name for path in tmp_path.iterdir()] == ["smoke.mp4"]


def test_governed_clip_refused_at_finalize_is_reported_as_skipped(
    tmp_path, monkeypatch
):
    """A governed clip keeps its bytes, but must not vanish from the run.

    Re-running Timestamp on a folder whose clips already carry the output
    name sends them through in-place replacement. A protected source
    refuses that, and the refusal used to appear only on stderr: no skip, no
    status, and the stamped temporary output stayed in the footage folder.
    """
    clip = tmp_path / "11-05-2026_14-30-00.mp4"
    clip.write_bytes(b"original bytes")

    worker = _worker(tmp_path)
    worker.files = [str(clip)]
    worker.get_camera_identity = lambda file_path: ""
    worker.get_metadata_timestamp = lambda file_path, camera_identity=None: (
        "2026:11:05 14:30:00",
        None,
    )
    worker.get_video_duration_seconds = lambda file_path: 10.0
    worker.should_skip_timestamp_overlay = lambda file_path, camera_identity: False

    def fake_burn(file_path, start_time_unix, output_file, progress_callback):
        Path(output_file).write_bytes(b"stamped bytes")
        return True

    worker.burn_timestamp = fake_burn
    worker.validate_processed_output = lambda output_file, duration: True
    monkeypatch.setattr(
        "timestamp.replacement_blocked_reason",
        lambda path: (
            "Files on a camera card are never edited in place."
        ),
    )

    statuses = []
    skipped = []
    worker.statusChanged.connect(statuses.append)
    worker.fileSkipped.connect(skipped.append)

    worker.process_videos(worker.files, lambda value: None)

    assert skipped == [str(clip)]
    assert worker.skipped_reasons == {str(clip): "replacement_refused"}
    assert any(
        "11-05-2026_14-30-00.mp4" in message
        and "camera card" in message
        for message in statuses
    )
    # The original is untouched and the stamped temporary output is gone.
    assert clip.read_bytes() == b"original bytes"
    assert [path.name for path in tmp_path.iterdir()] == [clip.name]


def test_finalize_io_failure_is_reported_and_cleans_the_temporary_output(
    tmp_path, monkeypatch
):
    """An I/O failure while replacing in place is a skip, not a disappearance."""
    clip = tmp_path / "11-05-2026_14-30-00.mp4"
    clip.write_bytes(b"original bytes")

    worker = _worker(tmp_path)
    worker.files = [str(clip)]
    worker.get_camera_identity = lambda file_path: ""
    worker.get_metadata_timestamp = lambda file_path, camera_identity=None: (
        "2026:11:05 14:30:00",
        None,
    )
    worker.get_video_duration_seconds = lambda file_path: 10.0
    worker.should_skip_timestamp_overlay = lambda file_path, camera_identity: False

    def fake_burn(file_path, start_time_unix, output_file, progress_callback):
        Path(output_file).write_bytes(b"stamped bytes")
        return True

    worker.burn_timestamp = fake_burn
    worker.validate_processed_output = lambda output_file, duration: True
    monkeypatch.setattr("timestamp.replacement_blocked_reason", lambda path: None)

    def failing_replace(source, destination):
        raise OSError("disk full")

    monkeypatch.setattr("timestamp.os.replace", failing_replace)

    statuses = []
    skipped = []
    worker.statusChanged.connect(statuses.append)
    worker.fileSkipped.connect(skipped.append)

    worker.process_videos(worker.files, lambda value: None)

    assert skipped == [str(clip)]
    assert worker.skipped_reasons == {str(clip): "finalize_failed"}
    assert any("disk full" in message for message in statuses)
    # finalize restored the original and the stamped temporary output is gone.
    assert clip.read_bytes() == b"original bytes"
    assert not [
        path for path in tmp_path.iterdir() if ".vts-tmp-" in path.name
    ]
