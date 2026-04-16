from PyQt5.QtCore import QThread, pyqtSignal, QSettings
import shutil
from pathlib import Path
import datetime  # Import the datetime module
import os
import subprocess
import sys
import re
import hashlib

from timestamp import get_resource_path

class ImportThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str, list)  # Emit the path of the new folder and the list of new files when finished
    error = pyqtSignal(str)

    def __init__(self, selected_date=None, destination_base=None, skip_duplicates=True):
        super().__init__()
        self.selected_date = selected_date
        self.destination_base = destination_base
        self.skip_duplicates = skip_duplicates
        self.was_cancelled = False
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def _should_stop(self):
        return self._stop_requested

    def run(self):
        try:
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

            # Check for AVCHD .MTS files, MP4 files, and LawMate MOV files created today
            files_to_copy = []
            seen_files = set()

            def append_if_on_target_date(file: Path):
                if file.name.startswith("._"):
                    return
                if datetime.date.fromtimestamp(file.stat().st_ctime) != target_date:
                    return
                file_key = str(file.resolve())
                if file_key in seen_files:
                    return
                seen_files.add(file_key)
                files_to_copy.append(file)

            if os.name == 'nt':  # Windows
                drives = [f"{chr(letter)}:\\" for letter in range(67, 91)]
            else:  # macOS
                drives = [str(volume) for volume in Path('/Volumes').iterdir() if volume.is_dir()]

            for drive in drives:
                drive_path = Path(drive)
                if drive_path.is_dir():
                    for root in ("PRIVATE", "private"):
                        stream_path = drive_path / root / 'AVCHD' / 'BDMV' / 'STREAM'
                        if stream_path.is_dir():
                            for file in stream_path.glob('*.MTS'):
                                append_if_on_target_date(file)
                        mp4_path = drive_path / root / 'M4ROOT' / 'CLIP'
                        if mp4_path.is_dir():
                            for file in mp4_path.glob('*.MP4'):
                                append_if_on_target_date(file)
                            for file in mp4_path.glob('*.mp4'):
                                append_if_on_target_date(file)
                    # Panasonic 4K and LawMate cards can place clips in day/media subfolders under DCIM.
                    dcim_path = drive_path / 'DCIM'
                    if dcim_path.is_dir():
                        for file in dcim_path.rglob('*'):
                            if file.is_file() and file.suffix.lower() in {'.mp4', '.mov'}:
                                append_if_on_target_date(file)

            # Copy the files and emit progress signals
            total = len(files_to_copy)
            if total == 0:
                self.progress.emit(100)
                self.finished.emit(str(folder_path), [])
                return

            def read_datetime_original(file_path: Path) -> datetime.datetime | None:
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
                    return datetime.datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S%z")
                except ValueError:
                    return None

            def expected_output_name(dt: datetime.datetime) -> str:
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

            def ledger_key_for_folder(target_folder: Path) -> str:
                digest = hashlib.sha1(str(target_folder).encode("utf-8")).hexdigest()
                return f"import_ledger/{digest}"

            def load_import_ledger(target_folder: Path) -> list[str]:
                ledger_entries = settings.value(ledger_key_for_folder(target_folder), [], type=list)
                if ledger_entries is None:
                    return []
                if isinstance(ledger_entries, list):
                    return [str(entry) for entry in ledger_entries]
                return [str(ledger_entries)]

            def fingerprint_for_file(file_path: Path, dt: datetime.datetime | None) -> str:
                size = file_path.stat().st_size
                if dt:
                    return f"{dt.isoformat()}|{size}|{file_path.name}"
                return f"NOEXIF|{size}|{file_path.name}"

            max_ledger_entries = 5000
            import_ledger_list = load_import_ledger(folder_path) if self.skip_duplicates else []
            import_ledger_set = set(import_ledger_list)
            ledger_updated = False

            new_files = []
            for i, file in enumerate(files_to_copy):
                if self._should_stop():
                    self.was_cancelled = True
                    self.finished.emit(str(folder_path), new_files)
                    return
                if self.skip_duplicates:
                    raw_dt = read_datetime_original(file)
                    fingerprint = fingerprint_for_file(file, raw_dt)
                    if fingerprint in import_ledger_set:
                        self.progress.emit((i + 1) * 100 // total)
                        continue
                    if raw_dt:
                        expected_name = expected_output_name(raw_dt)
                        expected_stem = Path(expected_name).stem
                        if (folder_path / expected_name).exists() or has_processed_match(expected_stem):
                            self.progress.emit((i + 1) * 100 // total)
                            continue
                destination = folder_path / file.name
                if not destination.exists():  # Only copy the file if it hasn't been copied already
                    shutil.copy(file, destination)
                    if self._should_stop():
                        self.was_cancelled = True
                        self.finished.emit(str(folder_path), new_files)
                        return
                new_files.append(str(destination))
                if self.skip_duplicates:
                    if fingerprint not in import_ledger_set:
                        import_ledger_set.add(fingerprint)
                        import_ledger_list.append(fingerprint)
                        if len(import_ledger_list) > max_ledger_entries:
                            overflow = len(import_ledger_list) - max_ledger_entries
                            for _ in range(overflow):
                                removed = import_ledger_list.pop(0)
                                import_ledger_set.discard(removed)
                        ledger_updated = True
                self.progress.emit((i + 1) * 100 // total)

            if ledger_updated:
                settings.setValue(ledger_key_for_folder(folder_path), import_ledger_list)

            # Emit the path of the new folder and the list of new files when finished
            self.finished.emit(str(folder_path), new_files)
        except PermissionError:
            self.error.emit(
                "Import failed because this destination is not writable. "
                "Choose another folder, or grant file access in System Settings > Privacy & Security > Files and Folders."
            )
        except OSError as exc:
            self.error.emit(f"Import failed while accessing the destination folder: {exc}")
