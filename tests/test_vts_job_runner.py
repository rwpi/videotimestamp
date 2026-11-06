import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import vts_job_runner


def _events(output: io.StringIO):
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_runner_streams_started_result_and_finished(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(
        vts_job_runner,
        "apply_workflow_settings",
        lambda action, options: dict(options or {}),
    )
    monkeypatch.setitem(
        vts_job_runner.RUNNERS,
        "video-minutes",
        lambda context, paths, options: setattr(
            context,
            "result",
            {"paths": paths, "options": options},
        ),
    )

    assert vts_job_runner.run_request(
        {"workflow": "video-minutes", "paths": ["one.mp4"], "options": {}},
        output,
    )

    events = _events(output)
    assert [event["event"] for event in events] == ["started", "result", "finished"]
    assert events[-1]["success"] is True


def test_runner_exposes_only_consolidated_native_workflows():
    assert not {
        "identify-subject",
        "revise-subject",
        "batch-processing",
        "camera-card-backup",
        "split",
    } & set(vts_job_runner.RUNNERS)
    assert vts_job_runner.RUNNERS["clip-order"] is vts_job_runner._run_organize
    assert vts_job_runner.RUNNERS["transcode"] is vts_job_runner._run_delivery
    # The experimental detection workflows are gone: trim is staged natively,
    # so the runner table carries the other seven presented tools and nothing else.
    assert set(vts_job_runner.RUNNERS) == {
        "import-files", "timestamp", "remove-audio", "clip-order",
        "video-minutes", "transcode", "merge",
    }


def test_delivery_preserves_quality_then_splits_only_oversized_outputs(monkeypatch, tmp_path):
    import video_splitter_gui
    import video_transcoder_gui

    class Signal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self, *values):
            for callback in self.callbacks:
                callback(*values)

    encoded = tmp_path / "clip_TRANSCODED.mp4"
    first_part = tmp_path / "clip_TRANSCODED_Part_1.mp4"
    second_part = tmp_path / "clip_TRANSCODED_Part_2.mp4"

    class FakeTranscodeWorker:
        def __init__(
            self,
            videos,
            quality,
            resolution,
            include_audio,
            maximum,
            *,
            output_mode="dedicated_folder",
            replace_size_limit_bytes=None,
        ):
            assert maximum is None
            assert output_mode == "dedicated_folder"
            self.status = Signal()
            self.progress = Signal()
            self.failed = Signal()
            self.finished = Signal()

        def run(self):
            encoded.touch()
            with encoded.open("r+b") as handle:
                handle.truncate(251_000_000)
            self.progress.emit(100)
            self.finished.emit([str(encoded)])

    class FakeSplitWorker:
        def __init__(self, videos, maximum, *, output_folder_name):
            assert videos == [encoded]
            assert maximum == 250_000_000
            assert output_folder_name == ""
            self.status = Signal()
            self.progress = Signal()
            self.failed = Signal()
            self.finished = Signal()

        def run(self):
            first_part.touch()
            second_part.touch()
            self.progress.emit(100)
            self.finished.emit([str(first_part), str(second_part)])

    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(
        vts_job_runner,
        "_selection",
        lambda paths: SimpleNamespace(files=(source,), working_folder=tmp_path),
    )
    monkeypatch.setattr(video_transcoder_gui, "TranscodeWorker", FakeTranscodeWorker)
    monkeypatch.setattr(video_splitter_gui, "SplitWorker", FakeSplitWorker)
    context = vts_job_runner.JobContext(vts_job_runner.EventWriter(io.StringIO()))

    vts_job_runner._run_delivery(
        context,
        [str(source)],
        {
            "quality": "balanced",
            "resolution": "original",
            "include_audio": True,
            "max_size_enabled": True,
            "max_size_gb": 0.25,
            "size_strategy": "preserve_quality",
            "output_mode": "dedicated_folder",
        },
    )

    assert not encoded.exists()
    assert context.result == {
        "outputs": [str(first_part), str(second_part)],
        "split_count": 2,
    }


def test_runner_rejects_trim_edits_outside_resolved_queue(monkeypatch, tmp_path):
    selected = tmp_path / "selected.mp4"
    selected.write_bytes(b"")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"")
    output = io.StringIO()
    monkeypatch.setattr(
        vts_job_runner,
        "apply_workflow_settings",
        lambda action, options: {"output_mode": "dedicated_folder"},
    )

    assert not vts_job_runner.run_request(
        {
            "workflow": "trim",
            "paths": [str(selected)],
            "options": {},
            "edits": [{"path": str(outside), "start": 1, "end": 2}],
        },
        output,
    )

    assert any(
        event.get("event") == "error" and "selected queue" in event.get("message", "")
        for event in _events(output)
    )


def test_runner_skips_stale_trim_edit_that_was_explicitly_selected(monkeypatch, tmp_path):
    current = tmp_path / "current.mp4"
    current.write_bytes(b"")
    archived = tmp_path / "already-archived.mp4"
    output = io.StringIO()
    monkeypatch.setattr(
        vts_job_runner,
        "apply_workflow_settings",
        lambda action, options: {"output_mode": "replace_and_archive"},
    )

    assert vts_job_runner.run_request(
        {
            "workflow": "trim",
            "paths": [str(current), str(archived)],
            "options": {},
            "edits": [{"path": str(archived), "start": 1, "end": 2}],
        },
        output,
    )

    events = _events(output)
    assert any(
        event.get("event") == "status" and "already archived" in event.get("message", "")
        for event in events
    )
    assert events[-1]["success"] is True


def test_trim_job_refuses_a_camera_card_source_before_writing(monkeypatch, tmp_path):
    """A trim output folder must never land on the only copy of the footage.

    The trim worker's own fallback keeps the original in place but still
    creates ``trimmed_clips`` beside it, which on a card mutates the card.
    The runner therefore refuses the job before any output directory exists,
    matching timestamp, merge, delivery and audio removal.
    """
    import original_archive
    import video_trimmer_gui

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"camera original")
    workers_built = []

    class FakeSignal:
        def connect(self, *_args):
            pass

    class FakeTrimWorker:
        status = progress = failed = finished = FakeSignal()

        def __init__(self, *args, **kwargs):
            workers_built.append(args)

        def run(self):
            # Mirrors the card fallback: the original stays put, but the
            # output folder lands beside it -- on the card.
            (tmp_path / "trimmed_clips").mkdir(exist_ok=True)

    monkeypatch.setattr(
        "native_trim_bridge.native_trim_files",
        lambda _paths, _options: [source],
    )
    monkeypatch.setattr(video_trimmer_gui, "TrimWorker", FakeTrimWorker)
    # A synthetic working folder stands in for a card; no /Volumes footage is
    # opened or changed by this regression check.
    monkeypatch.setattr(
        original_archive,
        "is_camera_card_path",
        lambda path: Path(path) == source,
    )

    with pytest.raises(vts_job_runner.JobRequestError, match="camera card"):
        vts_job_runner._run_trim(
            vts_job_runner.JobContext(vts_job_runner.EventWriter(io.StringIO())),
            [str(source)],
            {
                "output_mode": "dedicated_folder",
                "use_hwaccel": False,
                "include_audio": False,
            },
            {"edits": [{"path": str(source), "start": 0, "end": 2}]},
        )

    assert workers_built == []
    assert not (tmp_path / "trimmed_clips").exists()
    assert not (tmp_path / "originals").exists()
    assert source.read_bytes() == b"camera original"


def _selection_merge_options(**overrides) -> dict:
    options = {
        "merge_mode": "selection",
        "client_delivery": False,
        "client_quality": "balanced",
        "client_max_size_gb": 4.5,
        "by_type": False,
        "output_mode": "replace_and_archive",
    }
    options.update(overrides)
    return options


def _record_merge_worker(monkeypatch) -> list:
    """Replace MergeWorker with a recorder; nothing is encoded."""
    import merge_clips_gui

    built: list = []

    class FakeSignal:
        def connect(self, *_args):
            pass

        def emit(self, *_args):
            pass

    class FakeMergeWorker:
        status = progress = failed = finished = FakeSignal()

        def __init__(self, folder, groups, **kwargs):
            built.append((folder, groups, kwargs))

        def run(self):
            pass

    monkeypatch.setattr(merge_clips_gui, "MergeWorker", FakeMergeWorker)
    return built


def test_merge_refuses_a_camera_card_output_folder_before_writing(
    monkeypatch, tmp_path
):
    """The explicit output folder is user-set and must be guarded too.

    Creating the destination folder already writes to a card, which holds the
    only copy of the footage, so the refusal happens before ``mkdir`` and
    before the worker is built.
    """
    import original_archive

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"evidence")
    card = tmp_path / "card"
    destination = card / "Merged"
    built = _record_merge_worker(monkeypatch)
    monkeypatch.setattr(
        vts_job_runner,
        "_selection",
        lambda *_args, **_kwargs: SimpleNamespace(
            files=[source], working_folder=tmp_path / "Merged"
        ),
    )
    monkeypatch.setattr(
        original_archive,
        "is_camera_card_path",
        lambda path: Path(path).resolve() == destination.resolve(),
    )

    with pytest.raises(vts_job_runner.JobRequestError, match="camera card"):
        vts_job_runner._run_merge(
            vts_job_runner.JobContext(vts_job_runner.EventWriter(io.StringIO())),
            [str(source)],
            _selection_merge_options(output_folder=str(destination)),
        )

    assert built == []
    assert not destination.exists()
    assert not card.exists()


def test_merge_still_runs_to_an_internal_disk_output_folder(
    monkeypatch, tmp_path
):
    """The card guard must not refuse an ordinary destination."""
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"evidence")
    destination = tmp_path / "Merged"
    built = _record_merge_worker(monkeypatch)
    monkeypatch.setattr(
        vts_job_runner,
        "_selection",
        lambda *_args, **_kwargs: SimpleNamespace(
            files=[source], working_folder=tmp_path
        ),
    )

    vts_job_runner._run_merge(
        vts_job_runner.JobContext(vts_job_runner.EventWriter(io.StringIO())),
        [str(source)],
        _selection_merge_options(output_folder=str(destination)),
    )

    assert destination.is_dir()
    assert len(built) == 1
    assert built[0][0] == destination


def test_persists_trim_request_before_processing(monkeypatch, tmp_path):
    monkeypatch.setenv("VTS_TRIM_RECOVERY_DIR", str(tmp_path))
    request = {
        "workflow": "trim",
        "paths": ["clip.mp4"],
        "options": {"output_mode": "replace_and_archive"},
        "edits": [{"path": "clip.mp4", "start": 1.25, "end": 2.5}],
    }

    vts_job_runner._persist_trim_recovery_request(request)

    latest = json.loads((tmp_path / "latest-trim-request.json").read_text())
    assert latest["request"] == request
    assert len(list(tmp_path.glob("trim-request-*.json"))) == 1


def test_ai_selection_can_expand_nested_day_folders(tmp_path):
    clips = [
        tmp_path / "2026-08-13" / "Zoom" / "Main" / "one.mp4",
        tmp_path / "2026-08-14" / "Zoom" / "Main" / "two.mov",
    ]
    for clip in clips:
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.touch()

    selection = vts_job_runner._selection([str(tmp_path)], recursive=True)

    assert set(selection.files) == {path.resolve() for path in clips}
    assert selection.working_folder == tmp_path.resolve()


def test_event_writer_rejects_non_finite_floats():
    """A non-finite float must fail here, not vanish in the client.

    ``_recorded_at`` returns ``float("inf")`` for a clip whose filename carries
    no stamp. Encoded with the default ``allow_nan`` that becomes the bare token
    ``Infinity``, which is not JSON: ``JSONSerialization`` rejects the line and
    the Swift reader skips it without logging, and nothing anywhere says so.
    """
    import pytest

    for value in (float("inf"), float("-inf"), float("nan")):
        output = io.StringIO()
        writer = vts_job_runner.EventWriter(output)
        with pytest.raises(ValueError):
            writer.emit("status", value=value)


def test_a_rejected_event_leaves_no_partial_line_behind():
    """json.dump streams, so it would already have written a fragment."""
    import pytest

    output = io.StringIO()
    writer = vts_job_runner.EventWriter(output)
    with pytest.raises(ValueError):
        writer.emit("status", message="fine so far", value=float("inf"))

    assert output.getvalue() == ""


def test_ordinary_events_still_round_trip():
    output = io.StringIO()
    writer = vts_job_runner.EventWriter(output)
    writer.emit("status", message="hello", value=1.5)

    assert _events(output) == [{"event": "status", "message": "hello", "value": 1.5}]


def test_apply_workflow_settings_never_persists_unsent_defaults(monkeypatch):
    """A default the user never chose is not a setting.

    Validation fills every unsent option with its schema default; persisting
    the filled map wrote defaults over stored preferences whenever a client
    launched with a partial map.
    """
    import finder_jobs

    written = {}

    class FakeSettings:
        def __init__(self, *args):
            pass

        def setValue(self, key, value):
            written[key] = value

        def sync(self):
            pass

    import PyQt5.QtCore

    monkeypatch.setattr(PyQt5.QtCore, "QSettings", FakeSettings)

    options = finder_jobs.apply_workflow_settings(
        "trim", {"include_audio": False}
    )

    assert "trim/output_mode" not in written
    assert written == {"trim/include_audio": False}
    # The validated result still carries the defaults for behavior.
    assert options["output_mode"]


def test_apply_workflow_settings_still_persists_what_was_sent(monkeypatch):
    import finder_jobs

    written = {}

    class FakeSettings:
        def __init__(self, *args):
            pass

        def setValue(self, key, value):
            written[key] = value

        def sync(self):
            pass

    import PyQt5.QtCore

    monkeypatch.setattr(PyQt5.QtCore, "QSettings", FakeSettings)

    finder_jobs.apply_workflow_settings("trim", {"output_mode": "dedicated_folder"})

    assert written.get("trim/output_mode") == "dedicated_folder"


def test_timestamp_run_that_skips_every_clip_says_why(tmp_path, monkeypatch):
    """A run that left every original untouched must not read "Complete"."""
    import timestamp

    first = tmp_path / "smoke-1.mp4"
    second = tmp_path / "smoke-2.mp4"
    first.touch()
    second.touch()

    class FakeWorker:
        def __init__(self, *_args):
            self.progressChanged = _Signal()
            self.statusChanged = _Signal()
            self.failed = _Signal()
            self.previewFrame = _Signal()
            self.fileProcessed = _Signal()
            self.fileSkipped = _Signal()
            self.outputCreated = _Signal()
            self.skipped_reasons = {}

        def run(self):
            for clip in (first, second):
                self.skipped_reasons[str(clip)] = timestamp.SKIP_REASON_MISSING_DATE
                self.fileSkipped.emit(str(clip))

    monkeypatch.setattr(timestamp, "Worker", FakeWorker)
    monkeypatch.setattr(
        vts_job_runner,
        "_selection",
        lambda paths: SimpleNamespace(
            files=(first, second),
            working_folder=tmp_path,
        ),
    )
    context = vts_job_runner.JobContext(vts_job_runner.EventWriter(io.StringIO()))

    vts_job_runner._run_timestamp(
        context,
        [str(first), str(second)],
        {
            "use_hwaccel": False,
            "remove_audio": False,
            "dst_fix": False,
            "add_hour": False,
            "subtract_hour": False,
            "date_format": "%m-%d-%Y",
            "skip_panasonic": False,
            "skip_viofo": False,
            "skip_lawmate": False,
            "retain_originals": True,
        },
    )

    assert context.result["processed_files"] == []
    assert context.result["outputs"] == []
    assert context.result["working_folder"] == str(tmp_path)
    assert context.result["summary"] == (
        "Skipped 2 clips: no embedded recording date; originals were left in place."
    )


def test_mixed_skip_reasons_each_get_a_phrase_that_follows_its_count():
    """A run that skipped for two reasons must still read as one sentence.

    The single-reason phrases complete "Skipped N clips: <phrase>", so a bare
    count glued on the front dropped the noun: "3 no embedded recording date".
    """
    five = ["/evidence/a.mp4", "/evidence/b.mp4", "/evidence/c.mp4",
            "/evidence/d.mp4", "/evidence/e.mp4"]
    reasons = {
        "/evidence/a.mp4": "missing_date",
        "/evidence/b.mp4": "missing_date",
        "/evidence/c.mp4": "missing_date",
        "/evidence/d.mp4": "finalize_failed",
        "/evidence/e.mp4": "finalize_failed",
    }

    assert vts_job_runner._skipped_clip_summary(five, reasons) == (
        "Skipped 5 clips: 3 with no embedded recording date and "
        "2 whose stamped copy could not be put in place; "
        "originals were left in place."
    )
    assert vts_job_runner._skipped_clip_summary(
        ["/evidence/a.mp4", "/evidence/d.mp4"],
        {"/evidence/a.mp4": "missing_date", "/evidence/d.mp4": "finalize_failed"},
    ) == (
        "Skipped 2 clips: 1 with no embedded recording date and "
        "1 whose stamped copy could not be put in place; "
        "originals were left in place."
    )


def test_replacement_refusal_and_finalize_failure_get_their_own_phrases():
    """A clip the finalize step refused must name itself in the summary.

    Finalize can refuse in-place replacement because a non-destructive case
    file governs the clip, or it can fail for I/O. Both are skips now, and
    each needs a phrase that completes "Skipped N clips: <phrase>".
    """
    assert vts_job_runner._skipped_clip_summary(
        ["/evidence/a.mp4"], {"/evidence/a.mp4": "replacement_refused"}
    ) == (
        "Skipped 1 clip: files on a camera card are never replaced; "
        "the original was left in place."
    )
    assert vts_job_runner._skipped_clip_summary(
        ["/evidence/a.mp4"], {"/evidence/a.mp4": "finalize_failed"}
    ) == (
        "Skipped 1 clip: the stamped copy could not be put in place; "
        "the original was left in place."
    )
    assert vts_job_runner._skipped_clip_summary(
        ["/evidence/a.mp4", "/evidence/b.mp4"],
        {
            "/evidence/a.mp4": "replacement_refused",
            "/evidence/b.mp4": "finalize_failed",
        },
    ) == (
        "Skipped 2 clips: 1 left on the camera card and "
        "1 whose stamped copy could not be put in place; "
        "originals were left in place."
    )


def test_any_runner_that_only_skipped_clips_gets_a_readable_summary(monkeypatch):
    """The guard covers future runners, not just timestamp's own result."""

    def fake_runner(context, _paths, _options):
        context.result = {
            "outputs": [],
            "skipped_files": ["/evidence/a.mp4"],
            "working_folder": "/evidence",
        }

    monkeypatch.setitem(vts_job_runner.RUNNERS, "timestamp", fake_runner)
    monkeypatch.setattr(
        vts_job_runner, "apply_workflow_settings", lambda *_a, **_k: {}
    )
    output = io.StringIO()

    assert vts_job_runner.run_request(
        {"workflow": "timestamp", "paths": ["/evidence/a.mp4"], "options": {}},
        output,
    )
    result = next(
        event["data"] for event in _events(output) if event["event"] == "result"
    )
    assert result["summary"] == (
        "Skipped 1 clip: nothing was timestamped; the original was left in place."
    )
    assert result["working_folder"] == "/evidence"


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *values):
        for callback in self.callbacks:
            callback(*values)
