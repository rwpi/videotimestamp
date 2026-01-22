from PyQt5.QtCore import QThread, pyqtSignal
import shutil
from pathlib import Path
import datetime  # Import the datetime module
import os

class ImportThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str, list)  # Emit the path of the new folder and the list of new files when finished

    def run(self):
        # Get today's date as a string
        today = datetime.date.today().isoformat()  # Use datetime.date.today().isoformat()

        # Determine the path to the user's Movies (macOS) or Videos (Windows) folder
        if os.name == 'nt':  # Windows
            folder_path = Path.home() / 'Videos' / today
        else:  # macOS
            folder_path = Path.home() / 'Movies' / today

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
                        # If the file was created today, add it to the list of files to copy
                        if datetime.date.fromtimestamp(file.stat().st_ctime) == datetime.date.today():
                            files_to_copy.append(file)

        # Copy the files and emit progress signals
        total = len(files_to_copy)
        if total == 0:
            self.progress.emit(100)
            self.finished.emit(str(folder_path), [])
            return

        new_files = []
        for i, file in enumerate(files_to_copy):
            destination = folder_path / file.name
            if not destination.exists():  # Only copy the file if it hasn't been copied already
                shutil.copy(file, destination)
            new_files.append(str(destination))
            self.progress.emit((i + 1) * 100 // total)

        # Emit the path of the new folder and the list of new files when finished
        self.finished.emit(str(folder_path), new_files)
