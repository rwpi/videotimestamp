#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PyQt5 import QtCore

from timestamp import get_bundled_ffmpeg_path
from original_archive import (
    ORIGINALS_FOLDER_NAME as SHARED_ORIGINALS_FOLDER_NAME,
    archive_original_and_publish,
    is_camera_card_path,
    unique_output_path,
)
from clip_utils import get_duration_seconds


VIDEO_EXTENSIONS = {".mts", ".mp4", ".mov", ".mkv", ".avi", ".m4v"}
OUTPUT_FOLDER_NAME = "transcoded_videos"
ORIGINALS_FOLDER_NAME = SHARED_ORIGINALS_FOLDER_NAME
TRANSCODE_OUTPUT_DEDICATED_FOLDER = "dedicated_folder"
TRANSCODE_OUTPUT_REPLACE_AND_ARCHIVE = "replace_and_archive"
# A re-encode that lost most of the recording must never be installed over the
# footage it came from, so a replacement has to look like its source first.
TRANSCODE_DURATION_TOLERANCE_SECONDS = 1.0
DEFAULT_QUALITY_PRESET = "balanced"
DEFAULT_RESOLUTION = "original"
@dataclass(frozen=True)
class TranscodePreset:
    key: str
    label: str
    description: str
    codec: str
    crf: int
    encoder_preset: str
    codec_label: str


TRANSCODE_PRESETS = (
    TranscodePreset(
        "high",
        "High Quality",
        "H.264 with very light compression; best when fine detail matters most.",
        "libx264",
        20,
        "medium",
        "H.264",
    ),
    TranscodePreset(
        "balanced",
        "Balanced (Recommended)",
        "H.264 with a strong size reduction and good 1080p client-delivery quality.",
        "libx264",
        23,
        "medium",
        "H.264",
    ),
    TranscodePreset(
        "compact",
        "Compact",
        "H.264 with more compression for smaller, widely compatible files.",
        "libx264",
        26,
        "medium",
        "H.264",
    ),
    TranscodePreset(
        "hevc",
        "Smallest (HEVC)",
        "H.265/HEVC saves more space, but some older client devices may not play it.",
        "libx265",
        25,
        "medium",
        "H.265/HEVC",
    ),
)
PRESETS_BY_KEY = {preset.key: preset for preset in TRANSCODE_PRESETS}
def get_transcode_preset(key: str) -> TranscodePreset:
    return PRESETS_BY_KEY.get(key, PRESETS_BY_KEY[DEFAULT_QUALITY_PRESET])


def transcode_output_name(source: Path) -> str:
    return f"{source.stem}_TRANSCODED.mp4"


def replacement_is_forbidden(source: Path) -> bool:
    """Whether this clip must keep its place on disk.

    Footage still on a camera card always does: the card holds the only copy
    until it is imported, so nothing may be moved out from under it.
    """
    return is_camera_card_path(source)


def staging_output_path(source: Path) -> Path:
    """A hidden sibling of ``source`` to encode into.

    A sibling because the publish step is an ``os.replace`` and that is only
    atomic within one filesystem. Tagged with the process id so two jobs
    working the same folder cannot pick the same staging name.
    """
    for attempt in range(1000):
        candidate = source.with_name(
            f".{source.stem}.vts-transcode-tmp-{os.getpid()}-{attempt}.mp4"
        )
        if not candidate.exists():
            return candidate
    raise OSError(f"Could not reserve a staging file beside {source.name}.")


def encoded_file_matches_source(staged: Path, source_duration: float) -> bool:
    """Whether ``staged`` is a plausible replacement for its source."""
    try:
        if staged.stat().st_size <= 0:
            return False
    except OSError:
        return False
    probed = get_duration_seconds(staged) or 0.0
    if probed <= 0:
        return False
    tolerance = max(TRANSCODE_DURATION_TOLERANCE_SECONDS, source_duration * 0.01)
    return abs(probed - source_duration) <= tolerance


# ffmpeg keeps -maxrate and -bufsize in signed 32-bit integers, and bufsize is
# written as twice the rate, so anything above ~1.07 Gb/s makes the encoder
# refuse to start. A short clip measured against a large size cap computes
# gigabits per second, which no delivery preset would ever use, so capping the
# limit here costs nothing and keeps the encoder arguments representable.
MAX_VIDEO_BITRATE_LIMIT = 100_000_000


def calculate_video_bitrate_limit(
    duration_seconds: float,
    max_output_bytes: int,
    include_audio: bool,
) -> int:
    if duration_seconds <= 0 or max_output_bytes <= 0:
        raise ValueError("Duration and maximum output size must be positive.")
    # Reserve four percent for the MP4 container, audio variance, and encoder
    # rate-control tolerance so a nominal 4.5 GB target remains safely below it.
    total_bits_per_second = int(
        max_output_bytes * 8 * 0.96 / duration_seconds
    )
    non_video_bits_per_second = 32_000 + (128_000 if include_audio else 0)
    video_bits_per_second = total_bits_per_second - non_video_bits_per_second
    if video_bits_per_second < 100_000:
        raise ValueError(
            "The selected file-size limit is too small for this video's runtime."
        )
    return min(video_bits_per_second, MAX_VIDEO_BITRATE_LIMIT)


def transcode_video_args(
    preset_key: str,
    resolution: str,
    max_video_bitrate: int | None = None,
) -> list[str]:
    preset = get_transcode_preset(preset_key)
    args: list[str] = [
        "-c:v",
        preset.codec,
        "-preset",
        preset.encoder_preset,
        "-crf",
        str(preset.crf),
        "-pix_fmt",
        "yuv420p",
    ]
    if preset.codec == "libx265":
        args.extend(["-tag:v", "hvc1"])
    if max_video_bitrate is not None:
        args.extend(
            [
                "-maxrate",
                str(max_video_bitrate),
                "-bufsize",
                str(max_video_bitrate * 2),
            ]
        )
    if resolution == "1080p":
        args.extend(
            [
                "-vf",
                "scale='min(1920,iw)':'min(1080,ih)':"
                "force_original_aspect_ratio=decrease:force_divisible_by=2",
            ]
        )
    elif resolution == "720p":
        args.extend(
            [
                "-vf",
                "scale='min(1280,iw)':'min(720,ih)':"
                "force_original_aspect_ratio=decrease:force_divisible_by=2",
            ]
        )
    return args


def build_transcode_command(
    ffmpeg: str,
    source: Path,
    output: Path,
    preset_key: str,
    resolution: str,
    include_audio: bool,
    max_output_bytes: int | None = None,
    duration_seconds: float | None = None,
) -> list[str]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-loglevel",
        "error",
        "-nostats",
        "-i",
        str(source),
        "-map",
        "0:v:0",
    ]
    if include_audio:
        command.extend(["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k"])
    else:
        command.append("-an")
    max_video_bitrate = None
    if max_output_bytes is not None:
        if duration_seconds is None:
            raise ValueError("Duration is required when limiting output size.")
        max_video_bitrate = calculate_video_bitrate_limit(
            duration_seconds,
            max_output_bytes,
            include_audio,
        )
    command.extend(
        transcode_video_args(preset_key, resolution, max_video_bitrate)
    )
    command.extend(
        [
            "-map_metadata",
            "0",
            "-map_chapters",
            "0",
            "-max_muxing_queue_size",
            "4096",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            str(output),
        ]
    )
    return command


class TranscodeWorker(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    failed = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(list)

    def __init__(
        self,
        videos: list[Path],
        preset_key: str = DEFAULT_QUALITY_PRESET,
        resolution: str = DEFAULT_RESOLUTION,
        include_audio: bool = True,
        max_output_bytes: int | None = None,
        *,
        output_mode: str = TRANSCODE_OUTPUT_DEDICATED_FOLDER,
        replace_size_limit_bytes: int | None = None,
    ):
        super().__init__()
        self.videos = videos
        self.preset_key = get_transcode_preset(preset_key).key
        self.resolution = resolution
        self.include_audio = include_audio
        self.max_output_bytes = max_output_bytes
        # A caller that forgets the argument, or sends something unrecognised,
        # gets the mode that writes beside the source. Defaulting the other way
        # would let a mistake upstream turn into moved footage.
        self.output_mode = (
            TRANSCODE_OUTPUT_REPLACE_AND_ARCHIVE
            if output_mode == TRANSCODE_OUTPUT_REPLACE_AND_ARCHIVE
            else TRANSCODE_OUTPUT_DEDICATED_FOLDER
        )
        self.replace_size_limit_bytes = replace_size_limit_bytes
        self._stop_requested = False
        self._process: subprocess.Popen | None = None
        self.was_cancelled = False

    def stop(self):
        self._stop_requested = True
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
        except OSError:
            try:
                process.kill()
            except OSError:
                pass

    def _encode_one(
        self,
        source: Path,
        output: Path,
        duration: float,
        completed_duration: float,
        total_duration: float,
    ) -> tuple[int, str]:
        command = build_transcode_command(
            get_bundled_ffmpeg_path(),
            source,
            output,
            self.preset_key,
            self.resolution,
            self.include_audio,
            self.max_output_bytes,
            duration,
        )
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            start_new_session=(os.name != "nt"),
        )
        diagnostic_lines: list[str] = []
        if self._process.stdout is not None:
            for raw_line in self._process.stdout:
                if self._stop_requested:
                    self.stop()
                    break
                line = raw_line.strip()
                if line.startswith("out_time_ms="):
                    try:
                        current = int(line.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    overall = completed_duration + min(duration, max(0.0, current))
                    self.progress.emit(min(99, round(overall * 100 / total_duration)))
                elif line and not line.startswith(
                    (
                        "frame=",
                        "fps=",
                        "stream_",
                        "bitrate=",
                        "total_size=",
                        "out_time=",
                        "dup_frames=",
                        "drop_frames=",
                        "speed=",
                        "progress=",
                    )
                ):
                    diagnostic_lines.append(line)
        return_code = self._process.wait()
        self._process = None
        return return_code, "\n".join(diagnostic_lines[-20:])

    @QtCore.pyqtSlot()
    def run(self):
        outputs: list[str] = []
        durations = [get_duration_seconds(video) or 0.0 for video in self.videos]
        total_duration = max(1.0, sum(durations))
        completed_duration = 0.0
        preset = get_transcode_preset(self.preset_key)
        try:
            for index, (source, duration) in enumerate(
                zip(self.videos, durations), start=1
            ):
                if self._stop_requested:
                    self.was_cancelled = True
                    break
                if duration <= 0:
                    raise RuntimeError(f"Could not determine the runtime of {source.name}.")
                mode = self.output_mode
                if mode == TRANSCODE_OUTPUT_REPLACE_AND_ARCHIVE:
                    if replacement_is_forbidden(source):
                        self.status.emit(
                            f"{source.name} is on a camera card; its "
                            "transcode is saved beside it instead."
                        )
                        mode = TRANSCODE_OUTPUT_DEDICATED_FOLDER
                    elif not source.is_file() or source.is_symlink():
                        self.status.emit(
                            f"{source.name} is not an ordinary file; its "
                            "transcode is saved beside it instead."
                        )
                        mode = TRANSCODE_OUTPUT_DEDICATED_FOLDER
                if mode == TRANSCODE_OUTPUT_REPLACE_AND_ARCHIVE:
                    output = staging_output_path(source)
                else:
                    output_folder = source.parent / OUTPUT_FOLDER_NAME
                    output_folder.mkdir(parents=True, exist_ok=True)
                    output = unique_output_path(
                        output_folder,
                        transcode_output_name(source),
                    )
                self.status.emit(
                    f"Transcoding {index} of {len(self.videos)}: {source.name} "
                    f"({preset.codec_label}, {preset.label})"
                )
                return_code, diagnostic = self._encode_one(
                    source,
                    output,
                    duration,
                    completed_duration,
                    total_duration,
                )
                if self._stop_requested:
                    self.was_cancelled = True
                    try:
                        output.unlink()
                    except OSError:
                        pass
                    break
                if return_code != 0:
                    try:
                        output.unlink()
                    except OSError:
                        pass
                    detail = diagnostic or "Unknown FFmpeg error"
                    raise RuntimeError(f"Could not transcode {source.name}: {detail}")
                if (
                    self.max_output_bytes is not None
                    and output.stat().st_size > self.max_output_bytes
                ):
                    actual_size = output.stat().st_size / 1_000_000_000
                    output.unlink()
                    raise RuntimeError(
                        f"{source.name} encoded to {actual_size:.2f} GB, above the "
                        "selected limit. No oversized client copy was kept."
                    )
                if mode == TRANSCODE_OUTPUT_REPLACE_AND_ARCHIVE:
                    if not encoded_file_matches_source(output, duration):
                        output.unlink(missing_ok=True)
                        raise RuntimeError(
                            f"The transcode of {source.name} did not match the "
                            "runtime of its source, so nothing was replaced."
                        )
                    if (
                        self.replace_size_limit_bytes is not None
                        and output.stat().st_size > self.replace_size_limit_bytes
                    ):
                        # Too big to stand in for the source. It still has to
                        # go somewhere, and the source keeps its place.
                        overflow_folder = source.parent / OUTPUT_FOLDER_NAME
                        overflow_folder.mkdir(parents=True, exist_ok=True)
                        destination = unique_output_path(
                            overflow_folder, transcode_output_name(source)
                        )
                        os.replace(output, destination)
                        output = destination
                        self.status.emit(
                            f"{source.name} was still above the delivery limit, "
                            "so its source was left in place."
                        )
                    else:
                        output = archive_original_and_publish(source, output)
                outputs.append(str(output))
                completed_duration += duration
                self.progress.emit(round(completed_duration * 100 / total_duration))
        except Exception as exc:
            self._process = None
            self.failed.emit(str(exc))
            return
        self.finished.emit(outputs)
