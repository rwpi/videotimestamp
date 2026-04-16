#!/usr/bin/env python3
import datetime
import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import QSettings

from hwaccel_filter import filter_hwaccel_methods
from timestamp import get_resource_path
from video_renamer_gui import get_duration_seconds


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}
TAG_SUFFIX_PATTERN = re.compile(
    r"(_(INTEGRITY|CLAIMANT|HUMAN|UNKNOWN|PERSON|SUBJECT|COVERT))+$",
    flags=re.IGNORECASE,
)
TIMESTAMP_PATTERN = re.compile(
    r"((?:\d{2}|[A-Za-z]{3})-(?:\d{2}|[A-Za-z]{3})-\d{4}_\d{2}-\d{2}-\d{2})",
    flags=re.IGNORECASE,
)


def preferred_date_order_from_settings() -> str | None:
    settings = QSettings("VideoTimestamp", "VTS")
    fmt = settings.value("date_format", "%m-%d-%Y")
    if isinstance(fmt, str):
        if fmt.startswith("%d"):
            return "DMY"
        if fmt.startswith("%m") or fmt.startswith("%b"):
            return "MDY"
    return None


def parse_clip_datetime(value: str, preferred_order: str | None = None) -> datetime.datetime | None:
    try:
        date_part, _ = value.split("_", 1)
        a_str, b_str, _ = date_part.split("-", 2)
        a_is_alpha = a_str.isalpha()
        b_is_alpha = b_str.isalpha()
        if not a_is_alpha:
            a = int(a_str)
        else:
            a = None
        if not b_is_alpha:
            b = int(b_str)
        else:
            b = None
    except ValueError:
        a = b = None
        a_is_alpha = b_is_alpha = False

    formats = []
    if a_is_alpha and not b_is_alpha:
        formats.append("%b-%d-%Y_%H-%M-%S")
    elif b_is_alpha and not a_is_alpha:
        formats.append("%d-%b-%Y_%H-%M-%S")
    elif a is not None and b is not None:
        if a > 12 and b <= 12:
            formats.append("%d-%m-%Y_%H-%M-%S")
        elif b > 12 and a <= 12:
            formats.append("%m-%d-%Y_%H-%M-%S")
        elif preferred_order == "DMY":
            formats.append("%d-%m-%Y_%H-%M-%S")
        elif preferred_order == "MDY":
            formats.append("%m-%d-%Y_%H-%M-%S")

    fallback_formats = [
        "%m-%d-%Y_%H-%M-%S",
        "%d-%m-%Y_%H-%M-%S",
        "%b-%d-%Y_%H-%M-%S",
        "%d-%b-%Y_%H-%M-%S",
    ]
    if not formats:
        formats = fallback_formats
    else:
        for fmt in fallback_formats:
            if fmt not in formats:
                formats.append(fmt)

    for fmt in formats:
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def extract_clip_datetime(path: Path) -> datetime.datetime | None:
    stem = re.sub(r"^CLIP\d+_", "", path.stem, flags=re.IGNORECASE)
    stem = TAG_SUFFIX_PATTERN.sub("", stem)
    match = TIMESTAMP_PATTERN.search(stem)
    if not match:
        return None
    return parse_clip_datetime(match.group(1), preferred_order=preferred_date_order_from_settings())


def is_merge_output(path: Path) -> bool:
    stem = path.stem.lower()
    return stem.startswith("merged_") or stem.endswith("_merged")


def classify_merge_group(path: Path) -> str:
    stem_upper = path.stem.upper()
    if stem_upper.endswith("_CLAIMANT"):
        return "claimant"
    if stem_upper.endswith("_INTEGRITY"):
        return "integrity"
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


def merge_output_name_for_clips(clips: list[Path]) -> str:
    clip_dates = [
        clip_datetime.date()
        for clip_datetime in (extract_clip_datetime(clip) for clip in clips)
        if clip_datetime is not None
    ]
    if not clip_dates:
        return "merged_clips.mp4"
    first_date = min(clip_dates)
    return f"{first_date.strftime('%m-%d-%Y')}_MERGED.mp4"


def natural_sort_key(value: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


class DroppableQueueList(QtWidgets.QListWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.owner.add_input_files(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.owner.remove_selected_input_files()
            event.accept()
            return
        super().keyPressEvent(event)


class MergeWorker(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(list)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, folder: Path, groups: list[tuple[str, list[Path]]]):
        super().__init__()
        self.folder = folder
        self.groups = groups
        settings = QSettings("VideoTimestamp", "VTS")
        self.use_hwaccel = settings.value("use_hwaccel", True, type=bool)
        self.hwaccel_method = filter_hwaccel_methods()
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

    def _merge_group(self, group_name: str, clips: list[Path]) -> Path:
        ffmpeg_path = get_resource_path("ffmpeg")
        base_name = merge_output_name_for_clips(clips)
        output_path = ensure_unique_output_path(self.folder, base_name)
        total_duration_seconds = sum(
            duration for duration in (get_duration_seconds(clip) for clip in clips) if duration is not None
        )

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            list_path = Path(handle.name)
            for clip in clips:
                escaped = str(clip).replace("\\", "\\\\").replace("'", "\\'")
                handle.write(f"file '{escaped}'\n")

        try:
            process = subprocess.Popen(
                [
                    ffmpeg_path,
                    "-hide_banner",
                    "-y",
                    "-loglevel",
                    "error",
                    "-nostats",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_path),
                    "-progress",
                    "pipe:1",
                    *self._video_encoder_args(),
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                start_new_session=(os.name != "nt"),
            )
            self._current_process = process

            if process.stdout is not None:
                for line in process.stdout:
                    if self._should_stop():
                        self._terminate_current_process()
                        break
                    line = line.strip()
                    if not line.startswith("out_time_ms=") or total_duration_seconds <= 0:
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

            stderr_output = ""
            if process.stderr is not None:
                stderr_output = process.stderr.read()
            return_code = process.wait()
        finally:
            self._current_process = None
            try:
                list_path.unlink()
            except OSError:
                pass

        if self._should_stop():
            self.was_cancelled = True
            try:
                output_path.unlink()
            except OSError:
                pass
            return output_path
        if return_code != 0:
            raise RuntimeError((stderr_output or "ffmpeg merge failed").strip())
        return output_path

    def _video_encoder_args(self) -> list[str]:
        if not self.use_hwaccel:
            return ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]

        encoder = self.hwaccel_method or "libx264"
        if encoder == "libx264":
            return ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]

        # Hardware encoders don't reliably accept libx264's preset/crf flags.
        return ["-c:v", encoder, "-b:v", "12M"]


class MainWindow(QtWidgets.QWidget):
    status_changed = QtCore.pyqtSignal(str)
    progress_changed = QtCore.pyqtSignal(int)
    run_started = QtCore.pyqtSignal()
    run_finished = QtCore.pyqtSignal()

    def __init__(self, initial_folder: str | None = None):
        super().__init__()
        self.setWindowTitle("Merge Clips")
        self.folder_path: Path | None = None
        self._thread = None
        self._worker = None
        self._clips: set[Path] = set()

        self.clip_list = DroppableQueueList(self)
        self.clip_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.clip_list.setStyleSheet("QListWidget { border: 1px dashed #4a4a4a; }")
        self.clip_list.setToolTip("Drag and drop video files here")
        self.file_queue_title = QtWidgets.QLabel("File Queue")
        self.file_queue_title.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.input_files_label = QtWidgets.QLabel("0 Input Files Selected")
        self.input_files_label.setStyleSheet("color: grey; font-size: 10px;")
        self.add_input_files_label = QtWidgets.QLabel('<a href="#">Add</a>')
        self.add_input_files_label.setStyleSheet("color: blue; font-size: 10px;")
        self.add_input_files_label.linkActivated.connect(self.choose_input_files)
        self.remove_input_files_label = QtWidgets.QLabel('<a href="#">Remove</a>')
        self.remove_input_files_label.setStyleSheet("color: blue; font-size: 10px;")
        self.remove_input_files_label.linkActivated.connect(self.remove_selected_input_files)
        self.reset_input_files_label = QtWidgets.QLabel('<a href="#">Reset</a>')
        self.reset_input_files_label.setStyleSheet("color: blue; font-size: 10px;")
        self.reset_input_files_label.linkActivated.connect(self.reset_input_files)
        self.output_folder_title = QtWidgets.QLabel("Output Folder")
        self.output_folder_title.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.output_folder_label = QtWidgets.QLabel("Output Folder:")
        self.output_folder_label.setStyleSheet("color: grey; font-size: 10px;")
        self.output_folder_label.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        self.output_folder_label.linkActivated.connect(self.open_folder)
        self.change_output_folder_label = QtWidgets.QLabel('<a href="#">Set</a>')
        self.change_output_folder_label.setStyleSheet("color: blue; font-size: 10px;")
        self.change_output_folder_label.linkActivated.connect(self.choose_output_folder)
        self.run_btn = QtWidgets.QPushButton("Merge Clips")

        input_files_row = QtWidgets.QHBoxLayout()
        input_files_row.addWidget(self.input_files_label)
        input_files_row.addStretch(1)
        input_files_row.addWidget(self.add_input_files_label)
        input_files_row.addWidget(self.remove_input_files_label)
        input_files_row.addWidget(self.reset_input_files_label)

        output_folder_row = QtWidgets.QHBoxLayout()
        output_folder_row.addWidget(self.output_folder_label)
        output_folder_row.addStretch(1)
        output_folder_row.addWidget(self.change_output_folder_label)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.file_queue_title)
        layout.addLayout(input_files_row)
        layout.addWidget(self.clip_list, 1)
        layout.addWidget(self.output_folder_title)
        layout.addLayout(output_folder_row)
        layout.addWidget(self.run_btn)

        self.run_btn.clicked.connect(self._handle_run_button)

        if initial_folder:
            self._set_folder_path(initial_folder)

    def _set_folder_path(self, path: str):
        cleaned = path.strip().strip('"').strip("'")
        if not cleaned:
            self.folder_path = None
            self.output_folder_label.setText("Output Folder:")
            self.change_output_folder_label.setText('<a href="#">Set</a>')
            return
        resolved = Path(cleaned).expanduser().resolve()
        self.folder_path = resolved
        self.output_folder_label.setText(f'Output Folder: <a href="#">{resolved.name}</a>')
        self.change_output_folder_label.setText('<a href="#">Change</a>')

    def choose_output_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Output Folder", str(self.folder_path) if self.folder_path else "")
        if path:
            self._set_folder_path(path)

    def open_folder(self):
        if self.folder_path:
            QtGui = QtWidgets.QApplication
            from PyQt5.QtGui import QDesktopServices
            from PyQt5.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder_path)))

    def choose_input_files(self):
        file_filter = "Video Files (*.MTS *.mts *.MP4 *.mp4 *.MOV *.mov *.MKV *.mkv *.AVI *.avi *.M4V *.m4v)"
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Select video files", "", file_filter)
        if paths:
            self.add_input_files(paths)

    def add_input_files(self, paths):
        valid_files = set()
        for path in paths:
            if not path:
                continue
            resolved = Path(path).expanduser()
            if not resolved.is_file():
                continue
            if resolved.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            if is_merge_output(resolved):
                continue
            valid_files.add(resolved.resolve())

        if not valid_files:
            return

        self._clips.update(valid_files)
        self._refresh_queue_display()

    def reset_input_files(self):
        self._clips = set()
        self._refresh_queue_display()

    def remove_selected_input_files(self):
        selected_files = {
            item.data(QtCore.Qt.UserRole)
            for item in self.clip_list.selectedItems()
            if item.data(QtCore.Qt.UserRole)
        }
        if not selected_files:
            return
        self._clips.difference_update(Path(path) for path in selected_files)
        self._refresh_queue_display()

    def _refresh_queue_display(self):
        self.clip_list.clear()
        for path in sorted(self._clips, key=lambda item: natural_sort_key(item.name)):
            self.clip_list.addItem(path.name)
            item = self.clip_list.item(self.clip_list.count() - 1)
            item.setData(QtCore.Qt.UserRole, str(path))
        self.input_files_label.setText(f"{len(self._clips)} Input Files Selected")

    def refresh_clips(self):
        # No auto-population. Merge queue is managed manually.
        self._refresh_queue_display()

    def _set_running(self, running: bool):
        self.run_btn.setText("Cancel" if running else "Merge Clips")
        self.run_btn.setEnabled(True)

    def _handle_run_button(self):
        if self._worker is not None:
            self._cancel_merge()
        else:
            self._start_merge()

    def _cancel_merge(self):
        if self._worker is None:
            return
        self.status_changed.emit("Cancelling Merge Clips")
        self.run_btn.setText("Cancelling...")
        self.run_btn.setEnabled(False)
        self._worker.stop()

    def _start_merge(self):
        if not self.folder_path or not self.folder_path.is_dir():
            QtWidgets.QMessageBox.warning(self, "Missing Folder", "Please select a folder.")
            return
        if not self._clips:
            QtWidgets.QMessageBox.warning(self, "No Clips", "Please add clips to the merge queue.")
            return

        groups = [("main", sorted(self._clips, key=lambda item: natural_sort_key(item.name)))]

        self._set_running(True)
        self.status_changed.emit("Starting merge")
        self.progress_changed.emit(0)
        self.run_started.emit()

        self._thread = QtCore.QThread()
        self._worker = MergeWorker(self.folder_path, groups)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self.status_changed.emit)
        self._worker.progress.connect(self.progress_changed.emit)
        self._worker.failed.connect(self._show_error)
        self._worker.failed.connect(self._thread.quit)
        self._worker.finished.connect(self._on_merge_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self.run_finished.emit)
        self._thread.finished.connect(lambda: self._set_running(False))
        self._thread.finished.connect(self._clear_worker_refs)
        self._thread.start()

    def _show_error(self, message: str):
        QtWidgets.QMessageBox.critical(self, "Merge Error", message)
        self.status_changed.emit(f"Merge failed: {message}")

    def _on_merge_finished(self, outputs: list[str]):
        was_cancelled = bool(self._worker and self._worker.was_cancelled)
        if was_cancelled:
            self.status_changed.emit("Merge Clips Cancelled")
        elif outputs:
            names = ", ".join(Path(path).name for path in outputs)
            self.status_changed.emit(f"Created {names}")
        if not was_cancelled:
            self.progress_changed.emit(100)

    def _clear_worker_refs(self):
        self._worker = None
        self._thread = None
