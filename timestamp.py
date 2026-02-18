import subprocess
import os
import datetime
import re
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal
import sys
import stat

def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
        if 'exiftool' in relative_path or 'ffmpeg' in relative_path:
            return os.path.basename(relative_path)

    # Add .exe extension if running on Windows
    if sys.platform == "win32" and ('exiftool' in relative_path or 'ffmpeg' in relative_path):
        relative_path += '.exe'

    # For macOS and Linux, ensure 'exiftool' is in a subdirectory
    elif 'exiftool' in relative_path and sys.platform != "win32":
        relative_path = os.path.join('exiftool', relative_path)

    full_path = os.path.join(base_path, relative_path)

    if 'exiftool' in relative_path:
        st = os.stat(full_path)
        os.chmod(full_path, st.st_mode | stat.S_IEXEC)

    return full_path

class Worker(QThread):
    progressChanged = pyqtSignal(int)
    progressDetail = pyqtSignal(int, int)
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
        skip_lawmate_timestamp=False,
        append_lawmate_covert_suffix=True,
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
        self.skip_lawmate_timestamp = skip_lawmate_timestamp
        self.append_lawmate_covert_suffix = append_lawmate_covert_suffix

    def run(self):
        self.process_videos(self.files, self.set_progress)
        self.finished.emit()

    def get_metadata_timestamp(self, file_path):
        if sys.platform == "darwin" and getattr(sys, "frozen", False):  # If the host machine is macOS
            exiftool_path = os.path.join(sys._MEIPASS, 'exiftool', 'exiftool') # Use the bundled exiftool
        else:
            exiftool_path = get_resource_path('exiftool')
        result = subprocess.run(
            [
                exiftool_path,
                '-s', '-s', '-s',
                '-DateTimeOriginal',
                '-CreateDate',
                '-MediaCreateDate',
                '-TrackCreateDate',
                '-CreationDateValue',
                '-LastUpdate',
                '-ModifyDate',
                '-TimeZone',
                file_path,
            ],
            capture_output=True,
            text=True,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        )
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
                else:
                    local_tz = datetime.datetime.now().astimezone().tzinfo
                    dt = dt.replace(tzinfo=local_tz)
            else:
                local_tz = datetime.datetime.now().astimezone().tzinfo
                dt = dt.replace(tzinfo=local_tz)
        if self.manually_adjusted_for_dst:
            dt = dt - datetime.timedelta(hours=1)  # Adjust for DST
        if self.add_hour:
            dt = dt + datetime.timedelta(hours=1)  # Add an hour
        if self.subtract_hour:
            dt = dt - datetime.timedelta(hours=1)  # Subtract an hour
        return int(dt.timestamp())

    def get_camera_identity(self, file_path):
        if sys.platform == "darwin" and getattr(sys, "frozen", False):
            exiftool_path = os.path.join(sys._MEIPASS, 'exiftool', 'exiftool')
        else:
            exiftool_path = get_resource_path('exiftool')
        result = subprocess.run(
            [
                exiftool_path,
                '-s', '-s', '-s',
                '-Make',
                '-CameraModelName',
                '-Model',
                '-Format',
                '-Information',
                file_path,
            ],
            capture_output=True,
            text=True,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        )
        values = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        return " ".join(values)

    def is_lawmate_file(self, file_path, camera_identity):
        identity_upper = camera_identity.upper()
        if "NVT-IM" in identity_upper or "CARDV-TURNKEY" in identity_upper:
            return True
        if Path(file_path).suffix.lower() == ".mov" and Path(file_path).name.upper().startswith("RECO"):
            return True
        return False

    def should_skip_timestamp_overlay(self, file_path, camera_identity):
        identity_upper = camera_identity.upper()
        if self.skip_panasonic_vx3_timestamp and "HC-VX3" in identity_upper:
            return True
        if self.skip_lawmate_timestamp and self.is_lawmate_file(file_path, camera_identity):
            return True
        return False

    def burn_timestamp(self, file_path, start_time_unix, output_file):
        if os.path.exists(output_file):
            return

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

        ffmpeg_path = get_resource_path("ffmpeg")
        command = (
            f'{ffmpeg_path} -hide_banner -i "{file_path}" -vf '
            f'"drawtext='
            f'text=\'%{{pts\\:localtime\\:{start_time_unix}\\:%X}}\': x=10: y=h-th-{offset_large}: fontsize={font_size}: fontcolor=white: shadowcolor=black: shadowx=2: shadowy=2, '
            f'drawtext='
            f'text=\'%{{pts\\:localtime\\:{start_time_unix}\\:{self.date_format}}}\': x=10: y=h-th-{offset_small}: fontsize={font_size}: fontcolor=white: shadowcolor=black: shadowx=2: shadowy=2'
        )
        source_bitrate_kbps = self.get_video_bitrate_kbps(file_path)
        command += f'" -c:v {self.hwaccel_method}'
        if source_bitrate_kbps:
            command += f' -b:v {source_bitrate_kbps}k'
        if self.remove_audio:
            command += ' -an'
        else:
            command += ' -map 0:v:0 -map 0:a:0? -c:a aac -b:a 192k -ac 2'
        command += f' "{output_file}"'
        result = subprocess.run(command, shell=True, capture_output=True, text=True, creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
        if result.stderr:
            print("Error:", result.stderr)
        if result.stdout:
            print("Output:", result.stdout)

    def transcode_without_timestamp(self, file_path, output_file):
        if os.path.exists(output_file):
            return
        ffmpeg_path = get_resource_path("ffmpeg")
        command = f'{ffmpeg_path} -hide_banner -i "{file_path}" -map 0:v:0 -c:v copy'
        if self.remove_audio:
            command += ' -an'
        else:
            command += ' -map 0:a:0? -c:a copy'
        command += f' "{output_file}"'
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        )
        if result.stderr:
            print("Error:", result.stderr)
        if result.stdout:
            print("Output:", result.stdout)

    def get_video_bitrate_kbps(self, file_path):
        ffmpeg_path = get_resource_path("ffmpeg")
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-i", file_path],
            capture_output=True,
            text=True,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        )
        output = (result.stderr or "") + (result.stdout or "")
        match = re.search(r"bitrate:\s*([0-9]+(?:\.[0-9]+)?)\s*kb/s", output, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            return int(float(match.group(1)))
        except ValueError:
            return None

    def get_video_dimensions(self, file_path):
        ffmpeg_path = get_resource_path("ffmpeg")
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-i", file_path],
            capture_output=True,
            text=True,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        )
        output = (result.stderr or "") + (result.stdout or "")
        for line in output.splitlines():
            if " Video: " in line and "x" in line:
                match = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
                if match:
                    return int(match.group(1)), int(match.group(2))
        return 0, 0

    def process_videos(self, files, set_progress):
        set_progress(0)

        total_files = len(files)
        increment = 100 / total_files if total_files else 0

        progress = 0

        for idx, file_path in enumerate(files, start=1):
            creation_date, tz_offset = self.get_metadata_timestamp(file_path)
            if creation_date:
                start_time_unix = self.to_unix_timestamp(creation_date, tz_offset=tz_offset)
                dt = datetime.datetime.fromtimestamp(start_time_unix)  # Convert the Unix timestamp back to a datetime
                camera_identity = self.get_camera_identity(file_path)
                lawmate_suffix = ""
                if self.append_lawmate_covert_suffix and self.is_lawmate_file(file_path, camera_identity):
                    lawmate_suffix = "_COVERT"
                output_file_name = (
                    f"{dt.strftime(self.date_format)}_{dt.strftime('%H-%M-%S')}{lawmate_suffix}.mp4"
                )
                output_file = os.path.join(self.output_folder_path, output_file_name)
                if self.should_skip_timestamp_overlay(file_path, camera_identity):
                    self.transcode_without_timestamp(file_path, output_file)
                else:
                    self.burn_timestamp(file_path, start_time_unix, output_file)

            progress += increment
            set_progress(int(progress))
            self.progressDetail.emit(idx, total_files)

    def set_progress(self, value):
        self.progressChanged.emit(value)
