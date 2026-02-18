import datetime
import os
import subprocess
from pathlib import Path


def _drive_roots():
    if os.name == "nt":
        return [Path(f"{chr(letter)}:\\") for letter in range(67, 91)]
    volumes_path = Path("/Volumes")
    if not volumes_path.is_dir():
        return []
    return [volume for volume in volumes_path.iterdir() if volume.is_dir()]


def _file_is_on_date(file_path: Path, selected_date: datetime.date) -> bool:
    try:
        return datetime.date.fromtimestamp(file_path.stat().st_ctime) == selected_date
    except OSError:
        return False


def _collect_source_folders_for_date(selected_date: datetime.date) -> list[Path]:
    source_folders = []
    seen = set()

    def add_folder_if_new(folder: Path):
        key = str(folder.resolve())
        if key in seen:
            return
        seen.add(key)
        source_folders.append(folder)

    for drive_path in _drive_roots():
        if not drive_path.is_dir():
            continue

        for root in ("PRIVATE", "private"):
            stream_path = drive_path / root / "AVCHD" / "BDMV" / "STREAM"
            if stream_path.is_dir():
                if any(
                    file.suffix.lower() == ".mts" and _file_is_on_date(file, selected_date)
                    for file in stream_path.glob("*")
                    if file.is_file() and not file.name.startswith("._")
                ):
                    add_folder_if_new(stream_path)

            mp4_path = drive_path / root / "M4ROOT" / "CLIP"
            if mp4_path.is_dir():
                if any(
                    file.suffix.lower() == ".mp4" and _file_is_on_date(file, selected_date)
                    for file in mp4_path.glob("*")
                    if file.is_file() and not file.name.startswith("._")
                ):
                    add_folder_if_new(mp4_path)

        dcim_path = drive_path / "DCIM"
        if dcim_path.is_dir():
            matching_dcim_folders = set()
            for file in dcim_path.rglob("*"):
                if not file.is_file() or file.name.startswith("._"):
                    continue
                if file.suffix.lower() not in {".mp4", ".mov"}:
                    continue
                if _file_is_on_date(file, selected_date):
                    matching_dcim_folders.add(file.parent)
            for folder in sorted(matching_dcim_folders):
                add_folder_if_new(folder)

    return source_folders


def show_sd_card_for_date(selected_date: datetime.date):
    for folder in _collect_source_folders_for_date(selected_date):
        if os.name == "nt":
            subprocess.run(["explorer", str(folder)])
        else:
            subprocess.run(["open", str(folder)])


def show_sd_card():
    show_sd_card_for_date(datetime.date.today())
