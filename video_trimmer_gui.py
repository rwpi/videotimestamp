#!/usr/bin/env python3
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path

from PyQt5 import QtCore
from PyQt5.QtCore import QSettings

from original_archive import (
    ORIGINALS_FOLDER_NAME as SHARED_ORIGINALS_FOLDER_NAME,
    is_camera_card_path,
    replacement_blocked_reason,
)
from hwaccel_filter import filter_hwaccel_methods
from merge_clips_gui import parse_clip_datetime, preferred_date_order_from_settings
from timestamp import get_bundled_ffmpeg_path, get_bundled_ffprobe_path


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".mts"}
TRIM_OUTPUT_DEDICATED_FOLDER = "dedicated_folder"
TRIM_OUTPUT_REPLACE_AND_ARCHIVE = "replace_and_archive"
TRIMMED_CLIPS_FOLDER_NAME = "trimmed_clips"
ORIGINALS_FOLDER_NAME = SHARED_ORIGINALS_FOLDER_NAME
TIMESTAMP_PATTERN = re.compile(
    r"((?:\d{2}|[A-Za-z]{3})-(?:\d{2}|[A-Za-z]{3})-\d{4}_\d{2}-\d{2}-\d{2})",
    flags=re.IGNORECASE,
)
def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def trim_output_directory_for(path: Path) -> Path:
    if path.parent.name == TRIMMED_CLIPS_FOLDER_NAME:
        return path.parent
    return path.parent / TRIMMED_CLIPS_FOLDER_NAME


def date_format_from_settings() -> str:
    settings = QSettings("VideoTimestamp", "VTS")
    date_format = settings.value("date_format", "%m-%d-%Y")
    if not isinstance(date_format, str) or not date_format:
        return "%m-%d-%Y"
    return date_format


def timestamp_adjusted_trim_path(path: Path, removed_seconds: float) -> Path:
    if removed_seconds <= 0:
        return path
    match = TIMESTAMP_PATTERN.search(path.stem)
    if not match:
        return path
    original_timestamp = match.group(1)
    dt = parse_clip_datetime(original_timestamp, preferred_order=preferred_date_order_from_settings())
    if dt is None:
        return path
    adjusted = dt + datetime.timedelta(seconds=removed_seconds)
    adjusted_label = f"{adjusted.strftime(date_format_from_settings())}_{adjusted.strftime('%H-%M-%S')}"
    stem = f"{path.stem[:match.start(1)]}{adjusted_label}{path.stem[match.end(1):]}"
    return path.with_name(f"{stem}{path.suffix}")


class TrimWorker(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        video_path: Path,
        start_seconds: float,
        end_seconds: float,
        output_mode: str,
        *,
        use_hwaccel: bool | None = None,
        remove_audio: bool | None = None,
    ):
        super().__init__()
        self.video_path = video_path
        self.start_seconds = max(0.0, start_seconds)
        self.end_seconds = max(self.start_seconds, end_seconds)
        self.output_mode = output_mode if output_mode in {
            TRIM_OUTPUT_DEDICATED_FOLDER,
            TRIM_OUTPUT_REPLACE_AND_ARCHIVE,
        } else TRIM_OUTPUT_REPLACE_AND_ARCHIVE
        settings = QSettings("VideoTimestamp", "VTS")
        self.use_hwaccel = (
            settings.value("use_hwaccel", True, type=bool)
            if use_hwaccel is None
            else bool(use_hwaccel)
        )
        self.remove_audio = (
            settings.value("remove_audio", True, type=bool)
            if remove_audio is None
            else bool(remove_audio)
        )
        self.hwaccel_method = filter_hwaccel_methods()
        self.was_cancelled = False
        self._stop_requested = False
        self._current_process = None

    def stop(self):
        self._stop_requested = True
        self._terminate_current_process()

    def _terminate_current_process(self):
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
        try:
            output = self._trim_video()
            if self._stop_requested:
                self.was_cancelled = True
                self.failed.emit("Trim cancelled.")
                return
            self.finished.emit(str(output))
        except Exception as exc:
            self.failed.emit(str(exc))

    def _encoder_args(self) -> list[str]:
        if not self.use_hwaccel:
            return ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]
        encoder = self.hwaccel_method or "libx264"
        if encoder == "libx264":
            return ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]
        source_bitrate = self._source_video_bitrate()
        target_bitrate = 6_000_000 if source_bitrate is None else int(source_bitrate * 1.10)
        target_bitrate = max(1_000_000, min(12_000_000, target_bitrate))
        return [
            "-c:v",
            encoder,
            "-b:v",
            str(target_bitrate),
            "-maxrate",
            str(int(target_bitrate * 1.35)),
            "-bufsize",
            str(target_bitrate * 2),
        ]

    def _source_video_bitrate(self) -> int | None:
        """Return a useful source bitrate without assuming stream metadata exists."""
        ffprobe_path = get_bundled_ffprobe_path()
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=bit_rate:format=bit_rate,duration",
                    "-of",
                    "json",
                    str(self.video_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return None
            payload = json.loads(result.stdout or "{}")
            streams = payload.get("streams") or []
            raw_bitrate = streams[0].get("bit_rate") if streams else None
            if raw_bitrate is None:
                raw_bitrate = (payload.get("format") or {}).get("bit_rate")
            if raw_bitrate is not None and int(raw_bitrate) > 0:
                return int(raw_bitrate)
            duration = float((payload.get("format") or {}).get("duration") or 0)
            if duration > 0 and self.video_path.is_file():
                return max(1, int(self.video_path.stat().st_size * 8 / duration))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return None

    def _has_audio_stream(self) -> bool:
        ffprobe_path = get_bundled_ffprobe_path()
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(self.video_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception:
            return False

    def _trim_video(self) -> Path:
        # Refuse before the encoder starts: the temporary file is written
        # beside the source, so on a card even a successful fallback would
        # grow the only copy of the evidence. Every job runner also rejects
        # this earlier; the worker check covers callers that bypass them.
        if is_camera_card_path(self.video_path):
            raise RuntimeError(
                "This clip is still on a camera card. VTS only ever copies "
                "from a card. Import it first, then trim the imported copy."
            )
        duration = max(0.001, self.end_seconds - self.start_seconds)
        temp_output = unique_path(self.video_path.with_name(f".{self.video_path.stem}_trimmed_tmp.mp4"))
        ffmpeg_path = get_bundled_ffmpeg_path()
        self.status.emit("Trimming video")

        cmd = [
            ffmpeg_path,
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-nostats",
            "-ss",
            f"{self.start_seconds:.3f}",
            "-i",
            str(self.video_path),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0",
            "-progress",
            "pipe:1",
        ]
        cmd.extend(self._encoder_args())
        if self._has_audio_stream() and not self.remove_audio:
            cmd.extend(["-map", "0:a:0?", "-c:a", "aac", "-b:a", "192k", "-ac", "2"])
        else:
            cmd.append("-an")
        cmd.extend(["-movflags", "+faststart", str(temp_output)])

        output_lines = []
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                start_new_session=(os.name != "nt"),
            )
            self._current_process = process
            if process.stdout is not None:
                for line in process.stdout:
                    if self._stop_requested:
                        self._terminate_current_process()
                        break
                    line = line.strip()
                    if line.startswith("out_time_ms="):
                        try:
                            out_time_ms = int(line.split("=", 1)[1])
                        except ValueError:
                            continue
                        self.progress.emit(max(0, min(99, int((out_time_ms / 1_000_000) / duration * 100))))
                    elif line and not line.startswith(("frame=", "fps=", "stream_", "bitrate=", "total_size=", "out_time=", "dup_frames=", "drop_frames=", "speed=", "progress=")):
                        output_lines.append(line)
            return_code = process.wait()
        finally:
            self._current_process = None

        if self._stop_requested:
            try:
                temp_output.unlink()
            except OSError:
                pass
            return self.video_path
        if return_code != 0:
            try:
                temp_output.unlink()
            except OSError:
                pass
            raise RuntimeError("\n".join(output_lines[-20:]) or "ffmpeg trim failed")

        final_output = timestamp_adjusted_trim_path(
            self.video_path,
            int(round(self.start_seconds)),
        )
        output_mode = self.output_mode
        if output_mode != TRIM_OUTPUT_DEDICATED_FOLDER and (
            replacement_blocked_reason(self.video_path) is not None
        ):
            # The original may not be moved, so the trim lands beside it.
            output_mode = TRIM_OUTPUT_DEDICATED_FOLDER
        if output_mode == TRIM_OUTPUT_DEDICATED_FOLDER:
            trimmed_dir = trim_output_directory_for(self.video_path)
            trimmed_dir.mkdir(exist_ok=True)
            final_output = unique_path(trimmed_dir / final_output.name)
        else:
            if final_output != self.video_path:
                final_output = unique_path(final_output)
            originals_dir = self.video_path.parent / ORIGINALS_FOLDER_NAME
            originals_dir.mkdir(exist_ok=True)
            original_destination = unique_path(originals_dir / self.video_path.name)
            shutil.move(str(self.video_path), str(original_destination))
        shutil.move(str(temp_output), str(final_output))
        self.progress.emit(100)
        return final_output
