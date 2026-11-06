#!/usr/bin/env python3
from __future__ import annotations

import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from PyQt5 import QtCore

from file_utils import unique_output_path
from timestamp import get_bundled_ffmpeg_path
from clip_utils import get_duration_seconds, natural_sort_key


VIDEO_EXTENSIONS = {".mts", ".mp4", ".mov", ".mkv", ".avi", ".m4v"}
MAX_PART_BYTES = 5_000_000_000
TARGET_PART_BYTES = 4_500_000_000
SPLIT_OUTPUT_FOLDER_NAME = "split_videos"
def calculate_segment_duration(
    source_size: int,
    duration_seconds: float,
    target_bytes: int = TARGET_PART_BYTES,
) -> float:
    if source_size <= 0 or duration_seconds <= 0 or target_bytes <= 0:
        raise ValueError("Video size, duration, and target size must be positive.")
    return max(1.0, duration_seconds * min(1.0, target_bytes / source_size))


def part_name(source: Path, index: int) -> str:
    return f"{source.stem}_Part_{index}{source.suffix.lower()}"


class SplitWorker(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    failed = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(list)

    def __init__(
        self,
        videos: list[Path],
        max_part_bytes: int = MAX_PART_BYTES,
        *,
        output_folder_name: str = SPLIT_OUTPUT_FOLDER_NAME,
    ):
        super().__init__()
        self.videos = videos
        self.max_part_bytes = max_part_bytes
        self.target_part_bytes = max(1, int(max_part_bytes * 0.9))
        self.output_folder_name = output_folder_name
        self._stop_requested = False
        self._process: subprocess.Popen | None = None
        self.was_cancelled = False

    def stop(self):
        self._stop_requested = True
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.send_signal(signal.SIGTERM)
            except OSError:
                pass

    def _run_ffmpeg(self, command: list[str]) -> tuple[int, str]:
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        _, stderr = self._process.communicate()
        return_code = self._process.returncode
        self._process = None
        return return_code, stderr or ""

    @QtCore.pyqtSlot()
    def run(self):
        outputs: list[str] = []
        try:
            ffmpeg = get_bundled_ffmpeg_path()
            total = max(1, len(self.videos))
            for file_index, source in enumerate(self.videos):
                if self._stop_requested:
                    self.was_cancelled = True
                    break
                if source.stat().st_size <= self.max_part_bytes:
                    self.status.emit(
                        f"Skipped {source.name}: already {self.max_part_bytes / 1_000_000_000:g} GB or smaller"
                    )
                    self.progress.emit(round((file_index + 1) * 100 / total))
                    continue

                duration = get_duration_seconds(source)
                if not duration:
                    raise RuntimeError(f"Could not determine the runtime of {source.name}.")

                self.status.emit(f"Splitting {source.name}")
                segment_duration = calculate_segment_duration(
                    source.stat().st_size,
                    duration,
                    self.target_part_bytes,
                )
                temp_dir = Path(tempfile.mkdtemp(prefix=".vts_split_", dir=str(source.parent)))
                try:
                    parts: list[Path] = []
                    for _attempt in range(8):
                        for old_part in temp_dir.iterdir():
                            if old_part.is_file():
                                old_part.unlink()
                        output_pattern = temp_dir / f"{source.stem}_part%03d{source.suffix.lower()}"
                        command = [
                            ffmpeg,
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-y",
                            "-i",
                            str(source),
                            "-map",
                            "0",
                            "-c",
                            "copy",
                            "-f",
                            "segment",
                            "-segment_time",
                            f"{segment_duration:.6f}",
                            "-reset_timestamps",
                            "1",
                            str(output_pattern),
                        ]
                        return_code, stderr = self._run_ffmpeg(command)
                        if self._stop_requested:
                            self.was_cancelled = True
                            break
                        if return_code != 0:
                            detail = stderr.strip().splitlines()[-1] if stderr.strip() else "Unknown FFmpeg error"
                            raise RuntimeError(f"Could not split {source.name}: {detail}")

                        parts = sorted(
                            (path for path in temp_dir.iterdir() if path.is_file()),
                            key=lambda path: natural_sort_key(path.name),
                        )
                        if not parts:
                            raise RuntimeError(f"FFmpeg did not create parts for {source.name}.")
                        largest = max(path.stat().st_size for path in parts)
                        if largest <= self.max_part_bytes:
                            break
                        segment_duration *= min(0.9, self.target_part_bytes / largest)
                    else:
                        raise RuntimeError(
                            f"Could not keep every part of {source.name} below "
                            f"{self.max_part_bytes / 1_000_000_000:g} GB."
                        )

                    if self.was_cancelled:
                        break
                    output_folder = (
                        source.parent / self.output_folder_name
                        if self.output_folder_name
                        else source.parent
                    )
                    output_folder.mkdir(parents=True, exist_ok=True)
                    for index, temporary_part in enumerate(parts, start=1):
                        destination = unique_output_path(
                            output_folder,
                            part_name(source, index),
                        )
                        temporary_part.replace(destination)
                        outputs.append(str(destination))
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)

                self.progress.emit(round((file_index + 1) * 100 / total))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(outputs)
