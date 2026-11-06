#!/usr/bin/env python3
"""Run VTS processing jobs without constructing any PyQt windows.

The Swift client starts one process per job and reads newline-delimited JSON
events from stdout.  Existing Python worker classes remain the implementation,
but their Qt signals are connected directly to this protocol instead of a GUI.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
from pathlib import Path
import signal
import sys
import threading
from typing import Any, Callable, TextIO

from finder_jobs import apply_workflow_settings, resolve_finder_selection
from workflow_schemas import WORKFLOW_SCHEMAS


class JobRequestError(ValueError):
    pass


class EventWriter:
    def __init__(self, output: TextIO) -> None:
        self.output = output
        self._lock = threading.Lock()

    def emit(self, event: str, **payload: Any) -> None:
        message = {"event": event, **payload}
        with self._lock:
            # dumps into one write, not dump. json.dump *streams*: a non-finite
            # float raises only after a partial, unterminated fragment is
            # already on stdout, and the runner's error handler then writes its
            # own event onto that same corrupt line. Worse, the default
            # allow_nan emits the bare token Infinity, which is not JSON --
            # JSONSerialization rejects the line and the Swift reader drops it
            # with no log and no counter, losing a whole identity group in
            # silence. Fail loudly in Python instead.
            self.output.write(
                json.dumps(
                    message,
                    default=_json_default,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
            self.output.write("\n")
            self.output.flush()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    raise TypeError(f"Cannot encode {type(value).__name__}")


class JobContext:
    def __init__(self, events: EventWriter) -> None:
        self.events = events
        self.worker: Any = None
        self.cancelled = False
        self.error: str | None = None
        self.result: Any = None

    def stop(self) -> None:
        self.cancelled = True
        worker = self.worker
        if worker is not None and hasattr(worker, "stop"):
            try:
                worker.stop()
            except Exception:
                pass

    def status(self, message: Any) -> None:
        text = str(message)
        self.events.emit("status", message=text)

    def progress(self, value: Any, *_unused: Any) -> None:
        try:
            percent = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return
        self.events.emit("progress", value=round(percent, 1))

    def fail(self, message: Any) -> None:
        self.error = str(message)
        self.events.emit("error", message=self.error)


ACTIVE_CONTEXT: JobContext | None = None


def _signal_handler(_signum: int, _frame: Any) -> None:
    if ACTIVE_CONTEXT is not None:
        ACTIVE_CONTEXT.stop()


def _selection(paths: Any, *, recursive: bool = False):
    if not isinstance(paths, list) or not paths or not all(
        isinstance(path, str) and path for path in paths
    ):
        raise JobRequestError("Add at least one video or folder.")
    try:
        selection = resolve_finder_selection(paths, recursive=recursive)
    except ValueError as error:
        raise JobRequestError(str(error)) from error
    if not selection.files:
        raise JobRequestError("The selection contains no supported video files.")
    return selection


def _connect_common_worker(
    context: JobContext,
    worker: Any,
    *,
    status_signal: str | None = "status",
    progress_signal: str | None = "progress",
    finished: Callable[..., None] | None = None,
) -> None:
    context.worker = worker
    if status_signal and hasattr(worker, status_signal):
        getattr(worker, status_signal).connect(context.status)
    if progress_signal and hasattr(worker, progress_signal):
        getattr(worker, progress_signal).connect(context.progress)
    if hasattr(worker, "failed"):
        worker.failed.connect(context.fail)
    if finished is not None and hasattr(worker, "finished"):
        worker.finished.connect(finished)


def _run_import(context: JobContext, _paths: Any, options: dict[str, Any]) -> None:
    from importtoday import ImportThread

    worker = ImportThread(
        selected_date=datetime.date.fromisoformat(options["import_date"]),
        destination_base=options["destination"],
        skip_duplicates=options["skip_duplicates"],
    )
    context.worker = worker
    worker.progress.connect(context.progress)
    worker.error.connect(context.fail)
    worker.finished.connect(
        lambda folder, files: setattr(
            context,
            "result",
            {"output_folder": folder, "files": list(files)},
        )
    )
    context.status("Scanning mounted camera media")
    worker.run()


_SKIP_REASON_PHRASES = {
    "missing_date": "no embedded recording date",
    "replacement_refused": "files on a camera card are never replaced",
    "finalize_failed": "the stamped copy could not be put in place",
}

# The single-reason phrases above complete "Skipped N clips: <phrase>", so they
# cannot follow a bare count. A run that skips for more than one reason needs
# phrases that read after "3 " and "2 ".
_MIXED_SKIP_REASON_PHRASES = {
    "missing_date": "with no embedded recording date",
    "replacement_refused": "left on the camera card",
    "finalize_failed": "whose stamped copy could not be put in place",
}

# Fixed order so a mixed sentence reads the same every time.
_SKIP_REASON_ORDER = (
    "missing_date",
    "replacement_refused",
    "finalize_failed",
)


def _skipped_clip_summary(
    skipped: list[str],
    reasons: dict[str, str] | None = None,
) -> str:
    """One sentence for a run that produced nothing but skipped clips.

    The Finder panel shows a result's ``summary`` verbatim. Without one, a
    timestamp job whose clips all lacked an embedded date ended on "Complete"
    with a Reveal button over the untouched originals.
    """
    counts: dict[str, int] = {}
    for path in skipped:
        reason = (reasons or {}).get(path, "unknown")
        key = reason if reason in _SKIP_REASON_PHRASES else "unknown"
        counts[key] = counts.get(key, 0) + 1
    count = len(skipped)
    noun = "clip" if count == 1 else "clips"
    if "unknown" in counts or not counts:
        detail = "nothing was timestamped"
    elif len(counts) == 1:
        (reason,) = counts
        detail = _SKIP_REASON_PHRASES[reason]
    else:
        detail = " and ".join(
            f"{counts[key]} {_MIXED_SKIP_REASON_PHRASES[key]}"
            for key in _SKIP_REASON_ORDER
            if counts.get(key)
        )
    original = "the original was" if count == 1 else "originals were"
    return f"Skipped {count} {noun}: {detail}; {original} left in place."


def _ensure_skipped_only_summary(result: Any) -> Any:
    """Give any runner's all-skipped result the sentence the panel can read.

    Timestamp reports the reasons itself; this covers a future runner that
    returns empty ``outputs`` beside a non-empty ``skipped_files`` without one.
    """
    if not isinstance(result, dict) or result.get("summary"):
        return result
    skipped = result.get("skipped_files")
    if not isinstance(skipped, list) or not skipped or result.get("outputs"):
        return result
    return {**result, "summary": _skipped_clip_summary([str(path) for path in skipped])}


def _run_timestamp(context: JobContext, paths: Any, options: dict[str, Any]) -> None:
    from hwaccel_filter import filter_hwaccel_methods
    from timestamp import Worker

    selection = _selection(paths)
    _reject_camera_card_sources(selection)
    worker = Worker(
        [str(path) for path in selection.files],
        str(selection.working_folder),
        filter_hwaccel_methods() if options["use_hwaccel"] else "libx264",
        options["remove_audio"],
        options["dst_fix"],
        options["add_hour"],
        options["subtract_hour"],
        options["date_format"],
        options["skip_panasonic"],
        options["skip_viofo"],
        options["skip_lawmate"],
        options["retain_originals"],
    )
    context.worker = worker
    worker.progressChanged.connect(context.progress)
    worker.statusChanged.connect(context.status)
    worker.failed.connect(context.fail)
    processed: list[str] = []
    skipped: list[str] = []
    outputs: list[str] = []
    worker.fileProcessed.connect(processed.append)
    worker.fileSkipped.connect(skipped.append)
    worker.outputCreated.connect(outputs.append)
    context.status(f"Timestamping {len(selection.files)} video(s)")
    worker.run()
    result = {
        "processed_files": processed,
        "skipped_files": skipped,
        "outputs": outputs,
        "working_folder": str(selection.working_folder),
    }
    if skipped and not processed:
        result["summary"] = _skipped_clip_summary(
            skipped,
            getattr(worker, "skipped_reasons", None),
        )
    context.result = result


def _run_organize(context: JobContext, paths: Any, options: dict[str, Any]) -> None:
    from clip_utils import organize_clips

    selection = _selection(paths)
    # Numbering renames clips in place, so on a card it would rename evidence.
    _reject_camera_card_sources(selection)
    files = list(selection.files)
    organize_clips(
        files,
        use_clip_numbers=bool(options.get("clip_numbers", True)),
        log=context.status,
    )
    context.result = {
        "working_folder": str(selection.working_folder),
        "files": [str(path) for path in files],
    }


def _run_count(context: JobContext, paths: Any, _options: dict[str, Any]) -> None:
    from classification_tags import SUBJECT_CLASSIFICATIONS, classification_from_filename
    from clip_utils import get_duration_seconds

    selection = _selection(paths)
    total_seconds = subject_seconds = 0.0
    integrity_count = unknown = 0
    total = len(selection.files)
    for index, path in enumerate(selection.files, start=1):
        if context.cancelled:
            return
        classification = classification_from_filename(path)
        if classification == "INTEGRITY":
            integrity_count += 1
        duration = get_duration_seconds(path)
        if duration is None:
            unknown += 1
        else:
            total_seconds += duration
            if classification in SUBJECT_CLASSIFICATIONS:
                subject_seconds += duration
        context.status(f"Counted {index}/{total}: {path.name}")
        context.progress(round(index * 100 / max(1, total)))
    context.result = {
        "kind": "video_runtime",
        "total_seconds": total_seconds,
        "subject_seconds": subject_seconds,
        "integrity_clips": integrity_count,
        "unknown_duration_clips": unknown,
        "clip_count": total,
    }


def _run_delivery(context: JobContext, paths: Any, options: dict[str, Any]) -> None:
    from video_splitter_gui import SplitWorker
    from video_transcoder_gui import TranscodeWorker

    selection = _selection(paths)
    _reject_camera_card_sources(selection)
    maximum = (
        round(float(options["max_size_gb"]) * 1_000_000_000)
        if options["max_size_enabled"]
        else None
    )
    preserve_quality = (
        maximum is not None and options.get("size_strategy") == "preserve_quality"
    )
    transcoded_outputs: list[str] = []
    worker = TranscodeWorker(
        list(selection.files),
        options["quality"],
        options["resolution"],
        options["include_audio"],
        None if preserve_quality else maximum,
        output_mode=options["output_mode"],
        replace_size_limit_bytes=maximum if preserve_quality else None,
    )
    context.worker = worker
    worker.status.connect(context.status)
    worker.progress.connect(
        (lambda value: context.progress(round(float(value) * 0.8)))
        if preserve_quality
        else context.progress
    )
    worker.failed.connect(context.fail)
    worker.finished.connect(lambda outputs: transcoded_outputs.extend(outputs))
    worker.run()
    if context.cancelled or context.error:
        return

    if not preserve_quality or maximum is None:
        context.result = {"outputs": transcoded_outputs}
        return

    transcoded = [Path(path) for path in transcoded_outputs]
    # A transcode that replaced its source occupies that source's path, and is
    # a working clip now: splitting it into parts would take the clip away
    # again. Only files that are not standing in for a source can be split.
    working_clips = {Path(path).resolve() for path in selection.files}
    oversized = [
        path
        for path in transcoded
        if path.resolve() not in working_clips and path.stat().st_size > maximum
    ]
    if not oversized:
        context.progress(100)
        context.result = {"outputs": transcoded_outputs, "split_count": 0}
        return

    context.status(
        f"Selected quality is above the delivery limit for {len(oversized)} "
        f"video(s); splitting those copies without re-encoding"
    )
    split_outputs: list[str] = []
    split_worker = SplitWorker(
        oversized,
        maximum,
        output_folder_name="",
    )
    context.worker = split_worker
    split_worker.status.connect(context.status)
    split_worker.progress.connect(
        lambda value: context.progress(80 + round(float(value) * 0.2))
    )
    split_worker.failed.connect(context.fail)
    split_worker.finished.connect(lambda outputs: split_outputs.extend(outputs))
    split_worker.run()
    if context.cancelled or context.error:
        return

    for intermediate in oversized:
        try:
            intermediate.unlink()
        except OSError as error:
            context.status(
                f"Prepared split parts, but could not remove temporary {intermediate.name}: {error}"
            )
    oversized_paths = {str(path) for path in oversized}
    final_outputs = [
        path for path in transcoded_outputs if path not in oversized_paths
    ] + split_outputs
    context.progress(100)
    context.result = {
        "outputs": final_outputs,
        "split_count": len(split_outputs),
    }


def _run_merge(context: JobContext, paths: Any, options: dict[str, Any]) -> None:
    from merge_clips_gui import (
        MergeWorker,
        classify_merge_group,
        merge_clip_sort_key,
    )

    worker_options = {
        "client_delivery": options["client_delivery"],
        "client_quality": options["client_quality"],
        "client_max_output_bytes": round(
            float(options["client_max_size_gb"]) * 1_000_000_000
        ),
    }
    selection = _selection(paths)
    _reject_camera_card_sources(selection)
    # Retain the explicit destination supported by legacy callers.
    destination = str(options.get("output_folder") or "").strip()
    if destination:
        output_folder = Path(destination).expanduser()
    else:
        output_folder = selection.working_folder
    # The destination is checked before it is created: making the folder would
    # already write to a card, which holds the only copy of the footage. The
    # default destination is derived from the guarded sources, but the
    # explicit one is user-set and was otherwise unguarded.
    _reject_camera_card_output(output_folder)
    if destination:
        try:
            output_folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise JobRequestError(
                f"Could not prepare the merged output folder: {error}"
            ) from error
        if not output_folder.is_dir():
            raise JobRequestError("The merged output folder is not a directory.")
    clips = sorted(selection.files, key=merge_clip_sort_key)
    if options["by_type"]:
        groups = [
            (name, [path for path in clips if classify_merge_group(path) == name])
            for name in ("subject", "integrity", "main")
        ]
        groups = [(name, group) for name, group in groups if group]
    else:
        groups = [("main", clips)]
    worker = MergeWorker(
        output_folder,
        groups,
        **worker_options,
    )
    def _merge_finished(outputs: Any) -> None:
        result: dict[str, Any] = {"outputs": list(outputs)}
        # Archive only after the merge actually produced something.
        if result["outputs"] and options["output_mode"] == "replace_and_archive":
            archived, kept = _archive_merged_inputs(groups, result["outputs"])
            result["archived_originals"] = archived
            if kept:
                result["kept_in_place"] = kept
        context.result = result

    _connect_common_worker(context, worker, finished=_merge_finished)
    worker.run()


def _run_trim(context: JobContext, paths: Any, options: dict[str, Any], request: dict[str, Any]) -> None:
    from native_trim_bridge import native_trim_files
    from clip_utils import get_duration_seconds
    from video_trimmer_gui import (
        TRIM_OUTPUT_DEDICATED_FOLDER,
        TrimWorker,
        timestamp_adjusted_trim_path,
        trim_output_directory_for,
    )

    if not isinstance(paths, list):
        raise JobRequestError("Add at least one video or folder.")
    files = native_trim_files(paths, options)
    if not files:
        raise JobRequestError("No clips match the selected trim source.")
    # Trimming writes a new clip. On a card that output folder would land on
    # the card itself, so refuse before any output directory is created --
    # the same rule every other writing workflow follows.
    _reject_camera_card_paths(files)
    edits = request.get("edits")
    if not isinstance(edits, list) or not edits:
        raise JobRequestError("Adjust at least one trim range before running the trim job.")
    allowed = {str(path.resolve()): path for path in files}
    outputs: list[str] = []

    selected_paths: list[Path] = []
    for raw_path in paths:
        try:
            selected_paths.append(Path(str(raw_path)).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            continue

    pending: list[tuple[Path, float, float]] = []
    for edit in edits:
        if not isinstance(edit, dict):
            raise JobRequestError("A trim edit does not belong to the selected queue.")
        try:
            edit_path = str(Path(str(edit.get("path"))).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            edit_path = ""
        if edit_path not in allowed:
            resolved_edit = Path(edit_path) if edit_path else None
            was_selected = resolved_edit is not None and any(
                resolved_edit == selected
                or (selected.is_dir() and resolved_edit.is_relative_to(selected))
                for selected in selected_paths
            )
            if was_selected:
                context.status(
                    f"Skipping unavailable or already archived clip: {resolved_edit.name}"
                )
                continue
            raise JobRequestError("A trim edit does not belong to the selected queue.")
        path = allowed[edit_path]
        start = float(edit.get("start", 0))
        end = float(edit.get("end", 0))
        if start < 0 or end <= start:
            raise JobRequestError(f"Invalid trim range for {path.name}.")

        if options["output_mode"] == TRIM_OUTPUT_DEDICATED_FOLDER:
            expected_name = timestamp_adjusted_trim_path(path, int(round(start))).name
            existing_output = trim_output_directory_for(path) / expected_name
            if existing_output.is_file():
                existing_duration = get_duration_seconds(existing_output)
                requested_duration = end - start
                if (
                    existing_duration is not None
                    and abs(existing_duration - requested_duration) <= 0.25
                ):
                    outputs.append(str(existing_output))
                    context.status(f"Keeping completed trim: {existing_output.name}")
                    continue
        pending.append((path, start, end))

    total = len(pending)
    if total == 0:
        context.progress(100)
        context.result = {"outputs": outputs}
        return

    for index, (path, start, end) in enumerate(pending, start=1):
        if context.cancelled:
            break
        worker = TrimWorker(
            path,
            start,
            end,
            options["output_mode"],
            use_hwaccel=options["use_hwaccel"],
            remove_audio=not options["include_audio"],
        )
        context.worker = worker
        worker.status.connect(context.status)
        worker.progress.connect(
            lambda value, base=index - 1: context.progress(
                round((base + int(value) / 100) * 100 / total)
            )
        )
        worker.failed.connect(context.fail)
        worker.finished.connect(outputs.append)
        context.status(f"Trimming {index}/{total}: {path.name}")
        worker.run()
        if context.error:
            break
    context.result = {"outputs": outputs}


def _persist_trim_recovery_request(request: Any) -> None:
    """Save native trim edits before processing so a UI session can be recovered."""
    if not isinstance(request, dict) or request.get("workflow") != "trim":
        return
    edits = request.get("edits")
    if not isinstance(edits, list) or not edits:
        return
    try:
        configured_dir = os.environ.get("VTS_TRIM_RECOVERY_DIR")
        if configured_dir:
            recovery_dir = Path(configured_dir).expanduser()
        elif sys.platform == "darwin":
            recovery_dir = Path.home() / "Library" / "Application Support" / "VTS" / "trim-recovery"
        else:
            state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            recovery_dir = state_root / "VTS" / "trim-recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        saved_at = datetime.datetime.now().astimezone()
        payload = {
            "saved_at": saved_at.isoformat(),
            "request": request,
        }
        encoded = json.dumps(payload, indent=2, sort_keys=True)
        timestamped = recovery_dir / f"trim-request-{saved_at.strftime('%Y%m%d-%H%M%S-%f')}.json"
        temporary = recovery_dir / ".latest-trim-request.json.tmp"
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, recovery_dir / "latest-trim-request.json")
        timestamped.write_text(encoded, encoding="utf-8")
    except (OSError, TypeError, ValueError):
        # Recovery logging must never prevent the actual trim job from running.
        return


def _reject_camera_card_output(output_folder: Any) -> None:
    """Refuse a job whose output folder is on a camera card.

    Source clips are checked separately. This covers a user-chosen
    destination: creating the folder would write to the card, which holds the
    only copy of the footage.
    """
    from original_archive import is_camera_card_path

    if not is_camera_card_path(output_folder):
        return
    raise JobRequestError(
        f"The output folder is on a camera card ({output_folder}). VTS only "
        "ever copies from a card. Choose a folder on the imported drive or an "
        "internal disk."
    )


def _reject_camera_card_sources(selection: Any) -> None:
    """Refuse to run a file-generating job against footage still on a card.

    Takes anything carrying ``.files`` -- a Finder selection or a tagger
    config. Jobs that resolve their own file list (trim) call
    ``_reject_camera_card_paths`` directly.
    """
    _reject_camera_card_paths(selection.files)


def _reject_camera_card_paths(files: Any) -> None:
    """Refuse file-generating work when any source clip is still on a card.

    Falling back to a dedicated output folder is not good enough here: that
    folder would be created on the card, which is still writing to the only
    copy of the footage. The card is copied from and nothing else, so the job
    stops before it does any work and says what to do instead.
    """
    from original_archive import is_camera_card_path

    on_card = [path for path in files if is_camera_card_path(path)]
    if not on_card:
        return
    shown = ", ".join(sorted(str(path) if path.is_dir() else path.name for path in on_card[:3]))
    if len(on_card) > 3:
        shown += f", and {len(on_card) - 3} more"
    raise JobRequestError(
        f"{len(on_card)} selected clip(s) are still on a camera card ({shown}). "
        "VTS only ever copies from a card. Import them first, then run this "
        "task on the imported copies."
    )


def _run_remove_audio(context: JobContext, paths: Any, options: dict[str, Any]) -> None:
    from audio_remover import AudioRemovalWorker

    selection = _selection(paths)
    _reject_camera_card_sources(selection)
    worker = AudioRemovalWorker(
        list(selection.files),
        output_mode=options["output_mode"],
    )
    context.worker = worker
    worker.status.connect(context.status)
    worker.progress.connect(context.progress)
    worker.failed.connect(context.fail)
    outputs: list[str] = []
    worker.finished.connect(lambda created: outputs.extend(created))
    context.status(f"Removing audio from {len(selection.files)} video(s)")
    worker.run()
    context.result = {
        "outputs": outputs,
        "output_folder": (
            str(Path(outputs[0]).parent) if outputs else None
        ),
    }


def _archive_merged_inputs(
    groups: Any, outputs: list[str]
) -> tuple[list[str], list[str]]:
    """Move every clip that fed a successful merge into ``originals/``.

    The merged video is the working copy now, so leaving its inputs beside it
    means the folder holds the same footage twice. Clips that must keep their
    place -- a camera card, a governed archive -- are reported instead, never
    moved.
    """
    from original_archive import archive_original, replacement_blocked_reason

    produced = {Path(path).resolve() for path in outputs}
    archived: list[str] = []
    kept: list[str] = []
    for _name, clips in groups:
        for clip in clips:
            clip_path = Path(clip)
            if not clip_path.is_file() or clip_path.resolve() in produced:
                continue
            if replacement_blocked_reason(clip_path) is not None:
                kept.append(str(clip_path))
                continue
            archived.append(str(archive_original(clip_path)))
    return archived, kept


RUNNERS: dict[str, Callable[[JobContext, Any, dict[str, Any]], None]] = {
    "import-files": _run_import,
    "timestamp": _run_timestamp,
    "remove-audio": _run_remove_audio,
    "clip-order": _run_organize,
    "video-minutes": _run_count,
    "transcode": _run_delivery,
    "merge": _run_merge,
}


def run_request(request: Any, output: TextIO = sys.stdout) -> bool:
    global ACTIVE_CONTEXT
    events = EventWriter(output)
    context = JobContext(events)
    ACTIVE_CONTEXT = context
    success = False
    workflow = ""
    try:
        if not isinstance(request, dict):
            raise JobRequestError("A job request must be a JSON object.")
        workflow = request.get("workflow")
        if not isinstance(workflow, str) or workflow not in WORKFLOW_SCHEMAS:
            raise JobRequestError(f"Unsupported workflow: {workflow!r}")
        options = apply_workflow_settings(workflow, request.get("options"))
        events.emit("started", workflow=workflow, process_id=os.getpid())
        if workflow == "trim":
            _run_trim(context, request.get("paths"), options, request)
        else:
            RUNNERS[workflow](context, request.get("paths"), options)
        if context.error:
            raise JobRequestError(context.error)
        success = not context.cancelled
        if context.result is not None:
            events.emit("result", data=_ensure_skipped_only_summary(context.result))
    except Exception as error:
        message = str(error)
        if not context.cancelled and context.error != message:
            events.emit("error", message=message)
        if not context.cancelled:
            context.error = message
    finally:
        events.emit(
            "finished",
            workflow=workflow,
            success=success,
            cancelled=context.cancelled,
        )
        ACTIVE_CONTEXT = None
    return success


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one headless VTS processing job")
    parser.add_argument("--request", action="store_true", required=True)
    parser.parse_args(argv)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as error:
        EventWriter(sys.stdout).emit("error", message=f"Invalid job request: {error}")
        return 2
    _persist_trim_recovery_request(request)
    protocol_output = sys.stdout
    # Third-party processing libraries occasionally print diagnostics. Keep
    # stdout reserved for the JSON event protocol consumed by Swift.
    sys.stdout = sys.stderr
    return 0 if run_request(request, protocol_output) else 2


if __name__ == "__main__":
    raise SystemExit(main())
