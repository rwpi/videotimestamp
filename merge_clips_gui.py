#!/usr/bin/env python3
from __future__ import annotations

import datetime
import os
import re
import signal
import subprocess
from collections import Counter
from pathlib import Path

from PyQt5 import QtCore
from PyQt5.QtCore import QSettings

from date_settings import preferred_date_order_from_settings
from file_utils import natural_sort_key, parse_clip_datetime
from hwaccel_filter import filter_hwaccel_methods
from original_archive import is_camera_card_path
from settings_coercion import optional_positive_float
from timestamp import get_bundled_ffmpeg_path, get_bundled_ffprobe_path
from clip_utils import get_duration_seconds


VIDEO_EXTENSIONS = {".mts", ".mp4", ".mov", ".mkv", ".avi", ".m4v"}
DEFAULT_CLIENT_DELIVERY_QUALITY = "balanced"
DEFAULT_CLIENT_DELIVERY_MAX_SIZE_GB = 4.5
CLIENT_DELIVERY_QUALITY_PRESETS = {
    "high": ("High Quality", 20, 8_000_000),
    "balanced": ("Balanced (Recommended)", 23, 5_000_000),
    "compact": ("Compact", 26, 3_000_000),
}
TAG_SUFFIX_PATTERN = re.compile(
    r"(_(INTEGRITY|CLAIMANT|HUMAN|UNKNOWN|CAR|PERSON|SUBJECT|COVERT))+$",
    flags=re.IGNORECASE,
)
TIMESTAMP_PATTERN = re.compile(
    r"((?:\d{2}|[A-Za-z]{3})-(?:\d{2}|[A-Za-z]{3})-\d{4}_\d{2}-\d{2}-\d{2})",
    flags=re.IGNORECASE,
)


def extract_clip_datetime(path: Path) -> datetime.datetime | None:
    stem = re.sub(r"^CLIP\d+_", "", path.stem, flags=re.IGNORECASE)
    stem = TAG_SUFFIX_PATTERN.sub("", stem)
    match = TIMESTAMP_PATTERN.search(stem)
    if not match:
        return None
    return parse_clip_datetime(match.group(1), preferred_order=preferred_date_order_from_settings())


#: Legacy CLAIMANT/HUMAN tags are subject video.
from classification_tags import SUBJECT_CLASSIFICATIONS


def classify_merge_group(path: Path) -> str:
    """Which reel a clip belongs in, going by its filename tag."""
    stem_upper = path.stem.upper()
    if stem_upper.endswith("_INTEGRITY"):
        return "integrity"
    if any(stem_upper.endswith(f"_{tag}") for tag in SUBJECT_CLASSIFICATIONS):
        return "subject"
    return "main"


def ensure_unique_output_path(folder: Path, base_name: str) -> Path:
    candidate = folder / base_name
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        numbered = folder / f"{candidate.stem}_{counter}{candidate.suffix}"
        if not numbered.exists():
            return numbered
        counter += 1


def merge_output_name_for_clips(clips: list[Path], group_name: str = "main") -> str:
    clip_dates = [
        clip_datetime.date()
        for clip_datetime in (extract_clip_datetime(clip) for clip in clips)
        if clip_datetime is not None
    ]
    if not clip_dates:
        if group_name == "main":
            return "merged_clips.mp4"
        else:
            return f"merged_{group_name}_clips.mp4"
    first_date = min(clip_dates)
    if group_name == "main":
        return f"{first_date.strftime('%m-%d-%Y')}_MERGED.mp4"
    else:
        return f"{first_date.strftime('%m-%d-%Y')}_{group_name.upper()}_MERGED.mp4"


def merge_clip_sort_key(path: Path):
    """Sort timestamped clips chronologically, regardless of CLIP number."""
    clip_datetime = extract_clip_datetime(path)
    if clip_datetime is not None:
        return (0, clip_datetime, natural_sort_key(path.name))
    return (1, datetime.datetime.max, natural_sort_key(str(path)))


# ffmpeg keeps -maxrate and -bufsize in signed 32-bit integers, and bufsize is
# written as twice the rate, so anything above ~1.07 Gb/s makes the encoder
# refuse to start. A short merge measured against a large size cap computes
# gigabits per second, which is far above every delivery preset, so capping the
# limit here costs nothing and keeps the encoder arguments representable.
MAX_CLIENT_VIDEO_BITRATE_LIMIT = 100_000_000


def calculate_client_video_bitrate_limit(
    duration_seconds: float,
    max_output_bytes: int,
    include_audio: bool,
) -> int:
    if duration_seconds <= 0 or max_output_bytes <= 0:
        raise ValueError("Duration and maximum output size must be positive.")
    total_bits_per_second = int(
        max_output_bytes * 8 * 0.96 / duration_seconds
    )
    non_video_bits_per_second = 32_000 + (192_000 if include_audio else 0)
    video_bits_per_second = total_bits_per_second - non_video_bits_per_second
    if video_bits_per_second < 100_000:
        raise ValueError(
            "The client-size limit is too small for this merged video's runtime."
        )
    return min(video_bits_per_second, MAX_CLIENT_VIDEO_BITRATE_LIMIT)


class MergeWorker(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(list)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        folder: Path,
        groups: list[tuple[str, list[Path]]],
        *,
        client_delivery: bool = False,
        client_quality: str = DEFAULT_CLIENT_DELIVERY_QUALITY,
        client_max_output_bytes: int = round(
            DEFAULT_CLIENT_DELIVERY_MAX_SIZE_GB * 1_000_000_000
        ),
    ):
        super().__init__()
        self.folder = folder
        self.groups = groups
        settings = QSettings("VideoTimestamp", "VTS")
        self.use_hwaccel = settings.value("use_hwaccel", True, type=bool)
        self.remove_audio = settings.value("remove_audio", True, type=bool)
        self.aspect_ratio_handling = settings.value("merge/aspect_ratio_handling", "letterbox")
        self.hwaccel_method = filter_hwaccel_methods()
        self.client_delivery = client_delivery
        self.client_quality = (
            client_quality
            if client_quality in CLIENT_DELIVERY_QUALITY_PRESETS
            else DEFAULT_CLIENT_DELIVERY_QUALITY
        )
        self.client_max_output_bytes = client_max_output_bytes
        self.was_cancelled = False
        self._stop_requested = False
        self._current_process = None

    def stop(self):
        self._stop_requested = True
        self._terminate_current_process()

    def _should_stop(self):
        return self._stop_requested

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
        outputs = []
        total_groups = len(self.groups)
        try:
            # The merged video is written into self.folder, so a folder on a
            # card would write onto the only copy of the footage. Every runner
            # checks first; this covers callers that do not, before anything
            # is encoded.
            if is_camera_card_path(self.folder):
                raise RuntimeError(
                    f"The output folder is on a camera card ({self.folder}). "
                    "VTS only ever copies from a card. Import its clips first, "
                    "then merge the imported copies."
                )
            for index, (group_name, clips) in enumerate(self.groups, start=1):
                if self._should_stop():
                    self.was_cancelled = True
                    break
                self.status.emit(f"Merging {group_name} clips")
                output_path = self._merge_group(group_name, clips)
                if self._should_stop():
                    self.was_cancelled = True
                    break
                outputs.append(str(output_path))
                self.progress.emit(int((index / total_groups) * 100))
            self.finished.emit(outputs)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _get_video_frame_rate(self, file_path: Path) -> float | None:
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
                    "stream=r_frame_rate",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                fps_str = result.stdout.strip()
                if "/" in fps_str:
                    num, denom = fps_str.split("/")
                    return float(num) / float(denom)
                else:
                    return float(fps_str)
        except Exception:
            pass
        return None

    def _get_video_resolution(self, file_path: Path) -> tuple[int, int] | None:
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
                    "stream=width,height",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 2:
                    try:
                        width = int(lines[0].strip())
                        height = int(lines[1].strip())
                        return (width, height)
                    except ValueError:
                        pass
        except Exception:
            pass
        return None

    def _has_audio_stream(self, file_path: Path) -> bool:
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
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception:
            return False

    def _build_concat_filter(
        self,
        clips: list[Path],
        target_resolution: tuple[int, int] | None,
        target_fps: float | None,
        audio_streams: list[bool],
        durations: list[float | None],
    ) -> tuple[str, list[str]]:
        filters = []
        concat_inputs = []
        include_audio = any(audio_streams) and not self.remove_audio

        for index, clip in enumerate(clips):
            video_chain = f"[{index}:v:0]settb=AVTB,setpts=PTS-STARTPTS"
            if target_resolution:
                width, height = target_resolution
                if self.aspect_ratio_handling == "stretch":
                    video_chain += f",scale={width}:{height}"
                else:
                    video_chain += (
                        f",scale={width}:{height}:force_original_aspect_ratio=decrease"
                        f",pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
                    )
            if target_fps:
                video_chain += f",fps={target_fps},setpts=N/({target_fps}*TB)"
            video_chain += ",setsar=1"
            video_label = f"v{index}"
            filters.append(f"{video_chain}[{video_label}]")
            concat_inputs.append(f"[{video_label}]")

            if include_audio:
                audio_label = f"a{index}"
                audio_chain = "asettb=AVTB,asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo"
                if audio_streams[index]:
                    filters.append(f"[{index}:a:0]{audio_chain}[{audio_label}]")
                else:
                    duration = durations[index] or get_duration_seconds(clip) or 0.001
                    filters.append(
                        "anullsrc=channel_layout=stereo:sample_rate=48000,"
                        f"atrim=0:duration={duration},{audio_chain}[{audio_label}]"
                    )
                concat_inputs.append(f"[{audio_label}]")

        audio_count = 1 if include_audio else 0
        output_labels = ["[v]"]
        if include_audio:
            output_labels.append("[a]")
        filters.append(
            f"{''.join(concat_inputs)}concat=n={len(clips)}:v=1:a={audio_count}{''.join(output_labels)}"
        )

        maps = ["-map", "[v]"]
        if include_audio:
            maps.extend(["-map", "[a]"])
        return ";".join(filters), maps

    def _merge_group(
        self,
        group_name: str,
        clips: list[Path],
        *,
        output_name: str | None = None,
    ) -> Path:
        ffmpeg_path = get_bundled_ffmpeg_path()
        base_name = output_name or merge_output_name_for_clips(clips, group_name)
        output_path = ensure_unique_output_path(self.folder, base_name)
        durations = [get_duration_seconds(clip) for clip in clips]
        total_duration_seconds = sum(duration for duration in durations if duration is not None)

        # Check user settings for manual override
        settings = QSettings("VideoTimestamp", "VTS")
        manual_resolution_str = settings.value('merge/target_resolution', None)
        # QSettings raises a QVariant/QMetaType conversion error when the
        # Swift UI stores Automatic as an empty string and `type=float` is
        # requested. Read the raw value and normalize it ourselves.
        manual_fps = optional_positive_float(
            settings.value('merge/target_fps', None)
        )
        
        target_fps = manual_fps
        target_resolution = None
        
        # Parse manual resolution if set
        if manual_resolution_str:
            parts = manual_resolution_str.split('x')
            if len(parts) == 2:
                try:
                    target_resolution = (int(parts[0]), int(parts[1]))
                except ValueError:
                    target_resolution = None
        
        # If automatic, detect most common across all clips
        if target_fps is None or target_resolution is None:
            if clips:
                frame_rates = []
                resolutions = []
                
                for clip in clips:
                    if target_fps is None:
                        fps = self._get_video_frame_rate(clip)
                        if fps:
                            frame_rates.append(fps)
                    if target_resolution is None:
                        res = self._get_video_resolution(clip)
                        if res:
                            resolutions.append(res)
                
                if target_fps is None and frame_rates:
                    target_fps = Counter(frame_rates).most_common(1)[0][0]
                if target_resolution is None and resolutions:
                    target_resolution = Counter(resolutions).most_common(1)[0][0]

        audio_streams = [self._has_audio_stream(clip) for clip in clips]
        filter_complex, output_maps = self._build_concat_filter(
            clips,
            target_resolution,
            target_fps,
            audio_streams,
            durations,
        )
        include_audio = any(audio_streams) and not self.remove_audio

        try:
            ffmpeg_cmd = [
                ffmpeg_path,
                "-hide_banner",
                "-y",
                "-loglevel",
                "error",
                "-nostats",
            ]
            for clip in clips:
                ffmpeg_cmd.extend(["-fflags", "+genpts", "-i", str(clip)])
            ffmpeg_cmd.extend([
                "-filter_complex",
                filter_complex,
                *output_maps,
                "-progress",
                "pipe:1",
            ])
            ffmpeg_cmd.extend(
                self._video_encoder_args(total_duration_seconds, include_audio)
            )
            if include_audio:
                ffmpeg_cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            else:
                ffmpeg_cmd.append("-an")
            ffmpeg_cmd.extend(["-movflags", "+faststart", str(output_path)])

            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                start_new_session=(os.name != "nt"),
            )
            self._current_process = process

            ffmpeg_output_lines = []
            if process.stdout is not None:
                for line in process.stdout:
                    if self._should_stop():
                        self._terminate_current_process()
                        break
                    line = line.strip()
                    if not line:
                        continue
                    if not line.startswith("out_time_ms="):
                        if not line.startswith(("frame=", "fps=", "stream_", "bitrate=", "total_size=", "out_time=", "dup_frames=", "drop_frames=", "speed=", "progress=")):
                            ffmpeg_output_lines.append(line)
                        continue
                    if total_duration_seconds <= 0:
                        continue
                    try:
                        out_time_ms = int(line.split("=", 1)[1])
                    except ValueError:
                        continue
                    progress_value = max(
                        0,
                        min(99, int((out_time_ms / 1_000_000) / total_duration_seconds * 100)),
                    )
                    self.progress.emit(progress_value)

            return_code = process.wait()
        finally:
            self._current_process = None

        if self._should_stop():
            self.was_cancelled = True
            try:
                output_path.unlink()
            except OSError:
                pass
            return output_path
        if return_code != 0:
            ffmpeg_output = "\n".join(ffmpeg_output_lines[-20:])
            raise RuntimeError((ffmpeg_output or "ffmpeg merge failed").strip())
        if (
            self.client_delivery
            and output_path.stat().st_size > self.client_max_output_bytes
        ):
            actual_size = output_path.stat().st_size / 1_000_000_000
            output_path.unlink()
            raise RuntimeError(
                f"The merged output encoded to {actual_size:.2f} GB, above the "
                "selected client-size limit. No oversized output was kept."
            )
        return output_path

    def _video_encoder_args(
        self,
        total_duration_seconds: float = 0.0,
        include_audio: bool = False,
    ) -> list[str]:
        if self.client_delivery:
            _label, crf, target_bitrate = CLIENT_DELIVERY_QUALITY_PRESETS[
                self.client_quality
            ]
            max_bitrate = calculate_client_video_bitrate_limit(
                total_duration_seconds,
                self.client_max_output_bytes,
                include_audio,
            )
            target_bitrate = min(target_bitrate, max_bitrate)
            encoder = self.hwaccel_method if self.use_hwaccel else "libx264"
            encoder = encoder or "libx264"
            if encoder == "libx264":
                return [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    str(crf),
                    "-maxrate",
                    str(max_bitrate),
                    "-bufsize",
                    str(max_bitrate * 2),
                ]
            return [
                "-c:v",
                encoder,
                "-b:v",
                str(target_bitrate),
                "-maxrate",
                str(max_bitrate),
                "-bufsize",
                str(max_bitrate * 2),
            ]

        if not self.use_hwaccel:
            return ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]

        encoder = self.hwaccel_method or "libx264"
        if encoder == "libx264":
            return ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]

        # Hardware encoders don't reliably accept libx264's preset/crf flags.
        return ["-c:v", encoder, "-b:v", "12M"]
