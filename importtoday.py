from PyQt5.QtCore import QThread, pyqtSignal, QSettings
import shutil
from pathlib import Path
import datetime  # Import the datetime module
import os
import subprocess
import sys
import re

from timestamp import get_resource_path

class ImportThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str, list)  # Emit the path of the new folder and the list of new files when finished

    def __init__(self, selected_date=None, destination_base=None):
        super().__init__()
        self.selected_date = selected_date
        self.destination_base = destination_base

    def run(self):
        # Get today's date as a string
        settings = QSettings("VideoTimestamp", "VTS")
        date_format = settings.value("date_format", "%m-%d-%Y")
        if not isinstance(date_format, str) or not date_format:
            date_format = "%m-%d-%Y"
        manually_adjusted_for_dst = settings.value("manually_adjusted_for_dst", False, type=bool)
        add_hour = settings.value("add_hour", False, type=bool)
        subtract_hour = settings.value("subtract_hour", False, type=bool)
        try:
            target_date = self.selected_date or datetime.date.today()
            date_label = target_date.strftime(date_format)
        except Exception:
            target_date = self.selected_date or datetime.date.today()
            date_label = target_date.isoformat()

        # Determine the path to the user's Movies (macOS) or Videos (Windows) folder
        if self.destination_base:
            base_path = Path(self.destination_base).expanduser()
        elif os.name == 'nt':  # Windows
            base_path = Path.home() / 'Videos'
        else:  # macOS
            base_path = Path.home() / 'Movies'

        folder_path = base_path / date_label

        # Create the new folder
        folder_path.mkdir(parents=True, exist_ok=True)

        # Check the STREAM folder for any .MTS files that were created today
        files_to_copy = []
        if os.name == 'nt':  # Windows
            drives = [f"{chr(letter)}:\\" for letter in range(67, 91)]
        else:  # macOS
            drives = [str(volume) for volume in Path('/Volumes').iterdir() if volume.is_dir()]

        for drive in drives:
            drive_path = Path(drive)
            if drive_path.is_dir():
                stream_path = drive_path / 'PRIVATE' / 'AVCHD' / 'BDMV' / 'STREAM'
                if stream_path.is_dir():
                    for file in stream_path.glob('*.MTS'):
                        if file.name.startswith("._"):
                            continue
                        # If the file was created on the selected date, add it to the list of files to copy
                        if datetime.date.fromtimestamp(file.stat().st_ctime) == target_date:
                            files_to_copy.append(file)

        # Copy the files and emit progress signals
        total = len(files_to_copy)
        if total == 0:
            self.progress.emit(100)
            self.finished.emit(str(folder_path), [])
            return

        def expected_output_name(file_path: Path) -> str | None:
            if sys.platform == "darwin" and getattr(sys, "frozen", False):
                exiftool_path = os.path.join(sys._MEIPASS, "exiftool", "exiftool")
            else:
                exiftool_path = get_resource_path("exiftool")
            result = subprocess.run(
                [exiftool_path, "-DateTimeOriginal", str(file_path)],
                capture_output=True,
                text=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            )
            if not result.stdout:
                return None
            date_str = result.stdout.strip().split(": ", 1)[-1]
            date_str = date_str.replace(" DST", "")
            try:
                dt = datetime.datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S%z")
            except ValueError:
                return None
            if manually_adjusted_for_dst:
                dt = dt - datetime.timedelta(hours=1)
            if add_hour:
                dt = dt + datetime.timedelta(hours=1)
            if subtract_hour:
                dt = dt - datetime.timedelta(hours=1)
            start_time_unix = int(dt.timestamp())
            local_dt = datetime.datetime.fromtimestamp(start_time_unix)
            return f"{local_dt.strftime(date_format)}_{local_dt.strftime('%H-%M-%S')}.mp4"

        def normalize_processed_stem(stem: str) -> str:
            stem = re.sub(r"^CLIP\d+_", "", stem, flags=re.IGNORECASE)
            stem = re.sub(
                r"(_(INTEGRITY|CLAIMANT|HUMAN|UNKNOWN|PERSON|SUBJECT|COVERT))+$",
                "",
                stem,
                flags=re.IGNORECASE,
            )
            return stem

        def has_processed_match(expected_stem: str) -> bool:
            for candidate in folder_path.glob("*.mp4"):
                if normalize_processed_stem(candidate.stem) == expected_stem:
                    return True
            return False

        new_files = []
        for i, file in enumerate(files_to_copy):
            expected_name = expected_output_name(file)
            if expected_name:
                expected_stem = Path(expected_name).stem
                if (folder_path / expected_name).exists() or has_processed_match(expected_stem):
                    self.progress.emit((i + 1) * 100 // total)
                    continue
            destination = folder_path / file.name
            if not destination.exists():  # Only copy the file if it hasn't been copied already
                shutil.copy(file, destination)
            new_files.append(str(destination))
            self.progress.emit((i + 1) * 100 // total)

        # Emit the path of the new folder and the list of new files when finished
        self.finished.emit(str(folder_path), new_files)
