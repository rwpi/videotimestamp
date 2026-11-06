from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

from PyQt5 import QtCore

from media_tool_paths import get_bundled_ffmpeg_path, get_bundled_ffprobe_path
from original_archive import (
    ORIGINALS_FOLDER_NAME,
    publish_beside_original,
    replacement_blocked_reason,
)


AUDIO_REMOVED_FOLDER_NAME = "Audio Removed"
REMOVE_AUDIO_REPLACE_AND_ARCHIVE = "replace_and_archive"
REMOVE_AUDIO_DEDICATED_FOLDER = "dedicated_folder"


def _probe_media(path: Path) -> tuple[float, set[str]]:
    result = subprocess.run(
        [
            get_bundled_ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Could not inspect {path.name}.")
    try:
        payload = json.loads(result.stdout or "{}")
        duration = float((payload.get("format") or {}).get("duration") or 0.0)
        stream_types = {
            str(stream.get("codec_type"))
            for stream in payload.get("streams", [])
            if stream.get("codec_type")
        }
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read media details for {path.name}.") from error
    return duration, stream_types


def _verified_silent_video(path: Path, expected_duration: float) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        duration, stream_types = _probe_media(path)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return False
    tolerance = max(2.0, expected_duration * 0.02)
    return (
        "video" in stream_types
        and "audio" not in stream_types
        and duration > 0
        and abs(duration - expected_duration) <= tolerance
    )


def _unique_output(path: Path) -> Path:
    if not path.exists():
        return path
    for counter in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise OSError(f"Could not create an output name beside {path}.")


class AudioRemovalWorker(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(list)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        files: list[Path],
        output_mode: str = REMOVE_AUDIO_REPLACE_AND_ARCHIVE,
    ):
        super().__init__()
        self.files = [Path(path).expanduser().resolve() for path in files]
        self.output_mode = (
            output_mode
            if output_mode in {REMOVE_AUDIO_REPLACE_AND_ARCHIVE, REMOVE_AUDIO_DEDICATED_FOLDER}
            else REMOVE_AUDIO_REPLACE_AND_ARCHIVE
        )
        self.was_cancelled = False
        self._stop_requested = False
        self._current_process: subprocess.Popen | None = None

    def stop(self):
        self._stop_requested = True
        process = self._current_process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def run(self):
        outputs: list[str] = []
        total = len(self.files)
        try:
            for index, source in enumerate(self.files, start=1):
                if self._stop_requested:
                    self.was_cancelled = True
                    break
                if source.parent.name == AUDIO_REMOVED_FOLDER_NAME:
                    self.status.emit(f"Skipping prior audio-removed output: {source.name}")
                    continue
                if source.parent.name == ORIGINALS_FOLDER_NAME:
                    # Selecting a whole folder now reaches the archive as well.
                    # An archived original is the copy being kept, not work.
                    self.status.emit(f"Skipping archived original: {source.name}")
                    continue
                if not source.is_file():
                    raise RuntimeError(f"The selected video is unavailable: {source}")
                source_duration, stream_types = _probe_media(source)
                if "video" not in stream_types or source_duration <= 0:
                    raise RuntimeError(f"No usable video stream was found in {source.name}.")
                # A card or a governed clip keeps its place; the copy still
                # gets made, it just lands in the dedicated folder instead.
                blocked = (
                    replacement_blocked_reason(source)
                    if self.output_mode == REMOVE_AUDIO_REPLACE_AND_ARCHIVE
                    else None
                )
                if blocked is not None:
                    self.status.emit(f"{source.name}: {blocked}")
                replacing = (
                    self.output_mode == REMOVE_AUDIO_REPLACE_AND_ARCHIVE
                    and blocked is None
                )
                output_name = f"{source.stem}.mp4"
                if replacing:
                    # The published name is the source's own, so it must not be
                    # uniquified away from it. Staging stays beside the source.
                    output = source.with_name(output_name)
                    temporary = source.with_name(
                        f".{source.stem}.vts-audio-tmp-{os.getpid()}.mp4"
                    )
                else:
                    output_directory = source.parent / AUDIO_REMOVED_FOLDER_NAME
                    expected_output = output_directory / output_name
                    if _verified_silent_video(expected_output, source_duration):
                        outputs.append(str(expected_output))
                        self.status.emit(
                            f"Keeping completed audio-free copy: {expected_output.name}"
                        )
                        self.progress.emit(round(index * 100 / max(1, total)))
                        continue
                    output_directory.mkdir(exist_ok=True)
                    output = _unique_output(expected_output)
                    temporary = output.with_name(
                        f".{output.stem}.vts-audio-tmp-{os.getpid()}{output.suffix}"
                    )
                if temporary.exists():
                    temporary.unlink()
                self.status.emit(f"Removing audio {index}/{total}: {source.name}")
                command = [
                    get_bundled_ffmpeg_path(),
                    "-hide_banner",
                    "-y",
                    "-loglevel",
                    "error",
                    "-nostats",
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-c:v",
                    "copy",
                    "-an",
                    "-map_metadata",
                    "0",
                    "-movflags",
                    "+faststart",
                    "-progress",
                    "pipe:1",
                    str(temporary),
                ]
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                    start_new_session=(os.name != "nt"),
                )
                self._current_process = process
                output_lines: list[str] = []
                try:
                    if process.stdout is not None:
                        for raw_line in process.stdout:
                            if self._stop_requested:
                                self.stop()
                                break
                            line = raw_line.strip()
                            if line.startswith(("out_time_ms=", "out_time_us=")):
                                try:
                                    seconds = int(line.split("=", 1)[1]) / 1_000_000.0
                                except ValueError:
                                    continue
                                file_progress = max(
                                    0.0,
                                    min(99.0, seconds * 100.0 / max(0.001, source_duration)),
                                )
                                overall = ((index - 1) + file_progress / 100.0) * 100.0 / max(1, total)
                                self.progress.emit(int(overall))
                            elif line and not line.startswith(
                                (
                                    "frame=", "fps=", "stream_", "bitrate=", "total_size=",
                                    "out_time=", "dup_frames=", "drop_frames=", "speed=", "progress=",
                                )
                            ):
                                output_lines.append(line)
                    return_code = process.wait()
                finally:
                    self._current_process = None
                if self._stop_requested:
                    self.was_cancelled = True
                    temporary.unlink(missing_ok=True)
                    break
                if return_code != 0:
                    temporary.unlink(missing_ok=True)
                    raise RuntimeError(
                        "\n".join(output_lines[-20:])
                        or f"ffmpeg could not remove audio from {source.name}."
                    )
                if not _verified_silent_video(temporary, source_duration):
                    temporary.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"The audio-free copy of {source.name} failed verification."
                    )
                if replacing:
                    output = publish_beside_original(source, temporary, output_name)
                else:
                    os.replace(temporary, output)
                outputs.append(str(output))
                self.progress.emit(round(index * 100 / max(1, total)))
            self.finished.emit(outputs)
        except Exception as error:
            self.failed.emit(str(error))
