import subprocess
import os
import datetime
import json
import re
import shutil
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal
import sys
import signal

from media_tool_paths import (
    get_bundled_exiftool_path,
    get_bundled_ffmpeg_path,
    get_bundled_ffprobe_path,
)
from original_archive import ORIGINALS_FOLDER_NAME, replacement_blocked_reason

VIOFO_FILENAME_PATTERNS = (
    # Newer dual-channel files, for example 2026_0518_081504_F.MP4.
    re.compile(r"^\d{4}_\d{4}_\d{6}_[FR]$", flags=re.IGNORECASE),
    # Older/generated VIOFO files, for example 2026_0518_081538_042803F.MP4.
    re.compile(r"^\d{4}_\d{4}_\d{6}_\d{5,6}[A-Z]?$", flags=re.IGNORECASE),
)

SKIP_REASON_MISSING_DATE = "missing_date"
# A governed clip refuses in-place replacement; an I/O failure at the same
# step is not a refusal, so it gets its own reason.
SKIP_REASON_REPLACEMENT_REFUSED = "replacement_refused"
SKIP_REASON_FINALIZE_FAILED = "finalize_failed"

class Worker(QThread):
    progressChanged = pyqtSignal(int)
    progressDetail = pyqtSignal(int, int)
    fileProcessed = pyqtSignal(str)
    fileSkipped = pyqtSignal(str)
    outputCreated = pyqtSignal(str)
    statusChanged = pyqtSignal(str)
    failed = pyqtSignal(str)
    finished = pyqtSignal()  

    def __init__(
        self,
        files,
        output_folder_path,
        hwaccel_method,
        remove_audio,
        manually_adjusted_for_dst,
        add_hour,
        subtract_hour,
        date_format,
        skip_panasonic_vx3_timestamp=False,
        skip_viofo_timestamp=True,
        skip_lawmate_timestamp=False,
        retain_originals=True,
    ):
        super().__init__()
        self.files = files
        self.output_folder_path = output_folder_path
        self.hwaccel_method = hwaccel_method
        self.remove_audio = remove_audio
        self.manually_adjusted_for_dst = manually_adjusted_for_dst
        self.add_hour = add_hour
        self.subtract_hour = subtract_hour
        self.date_format = date_format
        self.skip_panasonic_vx3_timestamp = skip_panasonic_vx3_timestamp
        self.skip_viofo_timestamp = skip_viofo_timestamp
        self.skip_lawmate_timestamp = skip_lawmate_timestamp
        self.retain_originals = retain_originals
        self.was_cancelled = False
        # Why a clip was left unstamped, keyed by path. The job runner turns
        # these into the sentence the Finder panel shows when nothing was
        # processed, so an all-skipped run is never reported as "Complete".
        self.skipped_reasons = {}
        self._stop_requested = False
        self._current_process = None
        self._last_command_error = ""
        # Set by finalize_processed_file so process_videos can report why a
        # clip was left alone instead of dropping it from the run.
        self._last_finalize_refusal = None
        self._last_finalize_error = ""

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
            if sys.platform != "win32":
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def run(self):
        self.process_videos(self.files, self.set_progress)
        self.finished.emit()

    def _run_command(self, command, *, shell=False):
        if self._should_stop():
            return None
        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "creationflags": (subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, shell=shell, **kwargs)
        self._current_process = process
        try:
            stdout, stderr = process.communicate()
        finally:
            self._current_process = None
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    def _run_ffmpeg_command(
        self,
        command,
        *,
        file_path,
        duration,
        start_time_unix,
        add_overlay,
        progress_callback,
    ):
        if self._should_stop():
            return False
        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
            "creationflags": (subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
        self._current_process = process
        output_lines = []
        try:
            if process.stdout is not None:
                for raw_line in process.stdout:
                    if self._should_stop():
                        self._terminate_current_process()
                        break
                    line = raw_line.strip()
                    if line.startswith(("out_time_ms=", "out_time_us=")):
                        try:
                            encoded_seconds = int(line.split("=", 1)[1]) / 1_000_000.0
                        except ValueError:
                            continue
                        percent = max(0.0, min(99.0, encoded_seconds * 100.0 / max(0.001, duration)))
                        progress_callback(percent)
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
        self._last_command_error = "\n".join(output_lines[-20:])
        if return_code != 0 or self._should_stop():
            return False
        progress_callback(100.0)
        return True

    def is_obs_file(self, file_path, camera_identity):
        identity_upper = camera_identity.upper()
        return "OBS STUDIO" in identity_upper or "OBS1" in identity_upper

    def paths_refer_to_same_file(self, first_path, second_path):
        try:
            return os.path.samefile(first_path, second_path)
        except OSError:
            first = os.path.normcase(os.path.abspath(first_path))
            second = os.path.normcase(os.path.abspath(second_path))
            return first == second

    def choose_output_file(self, file_path, output_file_name):
        """A free output path, keeping a clip on a name it already owns.

        Two clips can share the embedded second import preserved, so the name
        derived from that second can already be held by a different clip.
        Stamp under ``_1``, ``_2`` ... instead of skipping. An already-stamped
        clip owns one of those names, so a candidate that is this same file
        wins: a re-run replaces it in place rather than stacking a counter.
        """
        base = Path(self.output_folder_path) / output_file_name
        candidate = base
        counter = 0
        while True:
            if self.paths_refer_to_same_file(file_path, candidate) or not candidate.exists():
                return candidate
            counter += 1
            candidate = base.with_name(f"{base.stem}_{counter}{base.suffix}")

    def get_temporary_output_file(self, output_file):
        output_path = Path(output_file)
        for counter in range(1000):
            candidate = output_path.with_name(
                f".{output_path.stem}.vts-tmp-{os.getpid()}-{counter}{output_path.suffix}"
            )
            if not candidate.exists():
                return str(candidate)
        raise OSError(f"Could not create a temporary output path for {output_file}")

    def move_original_file(self, file_path):
        if replacement_blocked_reason(file_path) is not None:
            # A camera card holds the only copy there is. Timestamping may
            # still create its derived output, but the
            # original must not be archived elsewhere or deleted just because
            # this machine's retain-originals preference says so.
            return None
        if self.retain_originals:
            originals_dir = os.path.join(self.output_folder_path, ORIGINALS_FOLDER_NAME)
            os.makedirs(originals_dir, exist_ok=True)
            destination = Path(originals_dir) / os.path.basename(file_path)
            if destination.exists():
                for counter in range(2, 10_000):
                    candidate = destination.with_name(
                        f"{destination.stem}_{counter}{destination.suffix}"
                    )
                    if not candidate.exists():
                        destination = candidate
                        break
                else:
                    raise OSError(f"Could not create an archive path for {file_path}")
            shutil.move(file_path, destination)
            return str(destination)
        else:
            os.remove(file_path)
            return None

    def finalize_processed_file(self, file_path, output_file, processing_output_file):
        self._last_finalize_refusal = None
        self._last_finalize_error = ""
        try:
            if self.paths_refer_to_same_file(file_path, output_file):
                blocked = replacement_blocked_reason(file_path)
                if blocked is not None:
                    self._last_finalize_refusal = blocked
                    raise OSError(blocked)
                if self.retain_originals:
                    archived_path = self.move_original_file(file_path)
                    try:
                        os.replace(processing_output_file, output_file)
                    except OSError:
                        if archived_path and not os.path.exists(file_path):
                            shutil.move(archived_path, file_path)
                        raise
                else:
                    backup_path = self.get_temporary_output_file(file_path)
                    os.replace(file_path, backup_path)
                    try:
                        os.replace(processing_output_file, output_file)
                    except OSError:
                        os.replace(backup_path, file_path)
                        raise
                    os.remove(backup_path)
            else:
                os.replace(processing_output_file, output_file)
                try:
                    self.move_original_file(file_path)
                except (OSError, shutil.Error) as error:
                    self.statusChanged.emit(
                        f"Created {Path(output_file).name}, but left the original in place: {error}"
                    )
            self.outputCreated.emit(str(output_file))
            return True
        except (OSError, shutil.Error) as e:
            self._last_finalize_error = str(e)
            print(f"Error finalizing processed file {file_path}: {e}")
            return False

    def report_finalize_skip(self, file_path):
        """Say why a clip was left alone after the stamped copy was made.

        ``finalize_processed_file`` returns False for a governed clip it
        refuses to replace in place (and for an I/O failure at the same
        step). Reporting only on stderr let the clip vanish from the run
        while the job still ended on "Complete".
        """
        refusal = self._last_finalize_refusal
        detail = (
            refusal
            or self._last_finalize_error
            or "the stamped copy could not be put in place"
        ).strip()
        if not detail.endswith("."):
            detail += "."
        self.statusChanged.emit(
            f"Skipped {Path(file_path).name}: {detail} The original was left in place."
        )
        self.skipped_reasons[file_path] = (
            SKIP_REASON_REPLACEMENT_REFUSED
            if refusal is not None
            else SKIP_REASON_FINALIZE_FAILED
        )
        self.fileSkipped.emit(file_path)

    def get_metadata_timestamp(self, file_path, camera_identity=None):
        exiftool_path = get_bundled_exiftool_path()
        if camera_identity is None:
            camera_identity = self.get_camera_identity(file_path)
        command = [
            exiftool_path,
            '-s', '-s', '-s',
        ]
        if self.is_obs_file(file_path, camera_identity):
            command.extend(['-api', 'QuickTimeUTC=1'])
        command.extend(
            [
                '-DateTimeOriginal',
                '-CreateDate',
                '-MediaCreateDate',
                '-TrackCreateDate',
                '-CreationDateValue',
                '-LastUpdate',
                '-ModifyDate',
                '-TimeZone',
                file_path,
            ]
        )
        result = self._run_command(
            command,
        )
        if result is None:
            return "", None
        if result.stderr:
            print("Error:", result.stderr)
        if result.stdout:
            print("Output:", result.stdout)
        timestamps = []
        tz_offset = None
        for line in result.stdout.splitlines():
            value = line.strip()
            if not value or value == "0000:00:00 00:00:00":
                continue
            if re.match(r"^[+-]\d{2}:?\d{2}$", value):
                tz_offset = value
                continue
            has_tz = bool(re.search(r"(Z|[+-]\d{2}:?\d{2})$", value))
            timestamps.append((value, has_tz))
        for value, has_tz in timestamps:
            if has_tz:
                return value, None
        return (timestamps[0][0], tz_offset) if timestamps else ("", tz_offset)

    def to_unix_timestamp(self, date_str, tz_offset=None):
        date_str = date_str.replace(" DST", "").strip()  # Remove ' DST' if present
        if date_str.endswith("Z"):
            date_str = f"{date_str[:-1]}+0000"
        try:
            dt = datetime.datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S%z')
        except ValueError:
            dt = datetime.datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
            if tz_offset:
                tz_match = re.match(r"^([+-])(\d{2}):?(\d{2})$", tz_offset)
                if tz_match:
                    sign, hours, minutes = tz_match.groups()
                    offset_minutes = int(hours) * 60 + int(minutes)
                    if sign == "-":
                        offset_minutes = -offset_minutes
                    dt = dt.replace(tzinfo=datetime.timezone(datetime.timedelta(minutes=offset_minutes)))
            # No embedded offset: leave dt naive so timestamp() applies the
            # local zone rule in force on the clip's date. Attaching
            # now().astimezone().tzinfo froze *today's* offset onto the clip,
            # which put a summer recording an hour out when processed in
            # winter (and the reverse), because fromtimestamp() renders with
            # the real zone rule for that date.
        if self.manually_adjusted_for_dst:
            dt = dt - datetime.timedelta(hours=1)  # Adjust for DST
        if self.add_hour:
            dt = dt + datetime.timedelta(hours=1)  # Add an hour
        if self.subtract_hour:
            dt = dt - datetime.timedelta(hours=1)  # Subtract an hour
        return int(dt.timestamp())

    def get_camera_identity(self, file_path):
        exiftool_path = get_bundled_exiftool_path()
        result = self._run_command(
            [
                exiftool_path,
                '-s', '-s', '-s',
                '-Make',
                '-CameraModelName',
                '-Model',
                '-Format',
                '-Information',
                '-Encoder',
                '-CompatibleBrands',
                file_path,
            ],
        )
        if result is None:
            return ""
        values = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        return " ".join(values)

    def is_lawmate_file(self, file_path, camera_identity):
        identity_upper = camera_identity.upper()
        if "NVT-IM" in identity_upper or "CARDV-TURNKEY" in identity_upper:
            return True
        if Path(file_path).suffix.lower() == ".mov" and Path(file_path).name.upper().startswith("RECO"):
            return True
        return False

    def is_viofo_file(self, file_path, camera_identity):
        identity_upper = camera_identity.upper()
        if "VIOFO" in identity_upper:
            return True
        stem = Path(file_path).stem
        if any(pattern.match(stem) for pattern in VIOFO_FILENAME_PATTERNS):
            return True
        return False

    def get_viofo_output_suffix(self, file_path, camera_identity):
        if not self.is_viofo_file(file_path, camera_identity):
            return ""
        stem = Path(file_path).stem
        match = re.search(r"(?:_|\d)([FR])$", stem, flags=re.IGNORECASE)
        if match:
            return f"_{match.group(1).upper()}"
        return ""

    def should_skip_timestamp_overlay(self, file_path, camera_identity):
        identity_upper = camera_identity.upper()
        if self.skip_panasonic_vx3_timestamp and "HC-VX3" in identity_upper:
            return True
        if self.skip_viofo_timestamp and self.is_viofo_file(file_path, camera_identity):
            return True
        if self.skip_lawmate_timestamp and self.is_lawmate_file(file_path, camera_identity):
            return True
        return False

    def burn_timestamp(self, file_path, start_time_unix, output_file, progress_callback):
        width, height = self.get_video_dimensions(file_path)
        if height:
            scale = height / 1080.0
            font_size = max(16, int(round(48 * scale)))
            offset_large = max(20, int(round(85 * scale)))
            offset_small = max(12, int(round(40 * scale)))
        else:
            font_size = 48
            offset_large = 85
            offset_small = 40

        ffmpeg_path = get_bundled_ffmpeg_path()
        filter_chain = (
            "drawtext="
            f"text='%{{pts\\:localtime\\:{start_time_unix}\\:%X}}': x=10: y=h-th-{offset_large}: fontsize={font_size}: fontcolor=white: shadowcolor=black: shadowx=2: shadowy=2, "
            "drawtext="
            f"text='%{{pts\\:localtime\\:{start_time_unix}\\:{self.date_format}}}': x=10: y=h-th-{offset_small}: fontsize={font_size}: fontcolor=white: shadowcolor=black: shadowx=2: shadowy=2"
        )
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-nostats",
            "-i",
            file_path,
            "-vf",
            filter_chain,
            "-c:v",
            self.hwaccel_method or "libx264",
        ]
        source_bitrate_kbps = self.get_video_bitrate_kbps(file_path)
        if source_bitrate_kbps:
            command.extend(["-b:v", f"{source_bitrate_kbps}k"])
        if self.remove_audio:
            command.append("-an")
        else:
            command.extend(["-map", "0:v:0", "-map", "0:a:0?", "-c:a", "aac", "-b:a", "192k", "-ac", "2"])
        command.extend(["-progress", "pipe:1", output_file])
        duration = self.get_video_duration_seconds(file_path) or 0.001
        return self._run_ffmpeg_command(
            command,
            file_path=file_path,
            duration=duration,
            start_time_unix=start_time_unix,
            add_overlay=True,
            progress_callback=progress_callback,
        )

    def transcode_without_timestamp(self, file_path, output_file, start_time_unix, progress_callback):
        ffmpeg_path = get_bundled_ffmpeg_path()
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-nostats",
            "-i",
            file_path,
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
        ]
        if self.remove_audio:
            command.append("-an")
        else:
            command.extend(["-map", "0:a:0?", "-c:a", "aac", "-b:a", "192k", "-ac", "2"])
        command.extend(["-progress", "pipe:1", output_file])
        duration = self.get_video_duration_seconds(file_path) or 0.001
        return self._run_ffmpeg_command(
            command,
            file_path=file_path,
            duration=duration,
            start_time_unix=start_time_unix,
            add_overlay=False,
            progress_callback=progress_callback,
        )

    def validate_processed_output(self, output_file, expected_duration):
        ffprobe_path = get_bundled_ffprobe_path()
        result = self._run_command(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "json",
                output_file,
            ]
        )
        if result is None or result.returncode != 0:
            return False
        try:
            payload = json.loads(result.stdout or "{}")
            stream_types = {stream.get("codec_type") for stream in payload.get("streams", [])}
            duration = float((payload.get("format") or {}).get("duration") or 0.0)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if "video" not in stream_types or duration <= 0:
            return False
        if self.remove_audio and "audio" in stream_types:
            return False
        tolerance = max(2.0, float(expected_duration or 0.0) * 0.02)
        return expected_duration is None or abs(duration - expected_duration) <= tolerance

    def get_video_bitrate_kbps(self, file_path):
        ffmpeg_path = get_bundled_ffmpeg_path()
        result = self._run_command(
            [ffmpeg_path, "-hide_banner", "-i", file_path],
        )
        if result is None:
            return None
        output = (result.stderr or "") + (result.stdout or "")
        match = re.search(r"bitrate:\s*([0-9]+(?:\.[0-9]+)?)\s*kb/s", output, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            return int(float(match.group(1)))
        except ValueError:
            return None

    def get_video_dimensions(self, file_path):
        ffmpeg_path = get_bundled_ffmpeg_path()
        result = self._run_command(
            [ffmpeg_path, "-hide_banner", "-i", file_path],
        )
        if result is None:
            return 0, 0
        output = (result.stderr or "") + (result.stdout or "")
        for line in output.splitlines():
            if " Video: " in line and "x" in line:
                match = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
                if match:
                    return int(match.group(1)), int(match.group(2))
        return 0, 0

    def get_video_duration_seconds(self, file_path):
        ffmpeg_path = get_bundled_ffmpeg_path()
        result = self._run_command(
            [ffmpeg_path, "-hide_banner", "-i", file_path],
        )
        if result is None:
            return None
        output = (result.stderr or "") + (result.stdout or "")
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
        if not match:
            return None
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    def process_videos(self, files, set_progress):
        set_progress(0)

        total_files = len(self.files)
        increment = 100 / total_files if total_files else 0

        progress = 0
        processed = 0

        while self.files:
            file_path = self.files.pop(0)
            processed += 1
            if self._should_stop():
                self.was_cancelled = True
                break
            camera_identity = self.get_camera_identity(file_path)
            creation_date, tz_offset = self.get_metadata_timestamp(
                file_path,
                camera_identity=camera_identity,
            )
            if self._should_stop():
                self.was_cancelled = True
                break
            if creation_date:
                start_time_unix = self.to_unix_timestamp(creation_date, tz_offset=tz_offset)
                if self.is_viofo_file(file_path, camera_identity):
                    duration = self.get_video_duration_seconds(file_path)
                    if duration is not None:
                        start_time_unix = int(round(start_time_unix - duration))
                dt = datetime.datetime.fromtimestamp(start_time_unix)  # Convert the Unix timestamp back to a datetime
                output_suffix = self.get_viofo_output_suffix(file_path, camera_identity)
                output_file_name = (
                    f"{dt.strftime(self.date_format)}_{dt.strftime('%H-%M-%S')}{output_suffix}.mp4"
                )
                output_file = str(
                    self.choose_output_file(file_path, output_file_name)
                )
                processing_output_file = self.get_temporary_output_file(output_file)
                duration = self.get_video_duration_seconds(file_path)
                def update_file_progress(file_percent):
                    overall = ((processed - 1) + float(file_percent) / 100.0) * 100.0 / max(1, total_files)
                    set_progress(int(max(0.0, min(99.0, overall))))
                finalized = False
                try:
                    if self.should_skip_timestamp_overlay(file_path, camera_identity):
                        success = self.transcode_without_timestamp(
                            file_path,
                            processing_output_file,
                            start_time_unix,
                            update_file_progress,
                        )
                    else:
                        success = self.burn_timestamp(
                            file_path,
                            start_time_unix,
                            processing_output_file,
                            update_file_progress,
                        )
                    if success:
                        success = self.validate_processed_output(
                            processing_output_file,
                            duration,
                        )
                        if not success:
                            self._last_command_error = "The completed file failed video, duration, or audio verification."
                    if success:
                        finalized = self.finalize_processed_file(
                            file_path,
                            output_file,
                            processing_output_file,
                        )
                        if finalized:
                            self.fileProcessed.emit(file_path)
                        elif not self._should_stop():
                            # The clip neither succeeded nor was reported
                            # skipped; say so instead of leaving it out of
                            # the result.
                            self.report_finalize_skip(file_path)
                    elif not self._should_stop():
                        detail = self._last_command_error or "ffmpeg did not create a valid output."
                        self.failed.emit(f"Could not timestamp {Path(file_path).name}: {detail}")
                        break
                finally:
                    # A failure after the temporary output exists must not
                    # leave the stamped file in the footage folder, where a
                    # later job would queue it as footage.
                    if not finalized and os.path.exists(processing_output_file):
                        try:
                            os.remove(processing_output_file)
                        except OSError as e:
                            print(f"Error deleting partial output {processing_output_file}: {e}")
                if self._should_stop():
                    self.was_cancelled = True
                    break
            else:
                # No embedded recording date: leave the clip unstamped rather
                # than inventing one, but never leave it out of the result.
                self.statusChanged.emit(
                    f"Skipped {Path(file_path).name}: no embedded recording date was found; the original was left in place."
                )
                self.skipped_reasons[file_path] = SKIP_REASON_MISSING_DATE
                self.fileSkipped.emit(file_path)

            progress += increment
            set_progress(int(progress))
            self.progressDetail.emit(processed, total_files)

    def set_progress(self, value):
        self.progressChanged.emit(value)
