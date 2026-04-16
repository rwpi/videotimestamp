#!/usr/bin/env python3
from pathlib import Path

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

from video_renamer_gui import get_duration_seconds


DEFAULT_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}
HUMAN_TAGS = ("HUMAN", "CLAIMANT", "SUBJECT")


class MainWindow(QtWidgets.QWidget):

    def __init__(self, initial_folder: str | None = None):
        super().__init__()
        self.setWindowTitle("Count Video")
        self.folder_path: Path | None = None

        self.folder_label = QtWidgets.QLabel("No folder selected")
        self.folder_label.setAlignment(Qt.AlignCenter)
        self.folder_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.folder_btn = QtWidgets.QPushButton("Browse...")
        if initial_folder:
            self._set_folder_path(initial_folder)

        self.count_btn = QtWidgets.QPushButton("Count Video")
        self.output_label = QtWidgets.QLabel("Ready.")
        self.output_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.output_label.setWordWrap(True)
        self.output_label.setStyleSheet("color: grey; font-size: 10px;")

        form = QtWidgets.QFormLayout()
        folder_row = QtWidgets.QHBoxLayout()
        folder_row.addWidget(self.folder_label)
        folder_row.addWidget(self.folder_btn)
        form.addRow("Folder", folder_row)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addStretch(1)
        layout.addLayout(form)
        layout.addWidget(self.count_btn)
        layout.addWidget(self.output_label)
        layout.addStretch(1)

        self.folder_btn.clicked.connect(self._choose_folder)
        self.count_btn.clicked.connect(self._count_tagged_minutes)

    def _choose_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            self._set_folder_path(path)

    def _set_folder_path(self, path: str):
        cleaned = path.strip().strip('"').strip("'")
        if not cleaned:
            self.folder_path = None
            self.folder_label.setText("No folder selected")
            return
        resolved = Path(cleaned).expanduser().resolve()
        self.folder_path = resolved
        self.folder_label.setText(resolved.name)

    def _count_tagged_minutes(self):
        if not self.folder_path:
            QtWidgets.QMessageBox.warning(self, "Missing Folder", "Please select a folder.")
            return
        if not self.folder_path.is_dir():
            QtWidgets.QMessageBox.warning(self, "Missing Folder", "Selected folder is not available.")
            return

        total_seconds = 0.0
        human_seconds = 0.0
        covert_seconds = 0.0
        integrity_count = 0
        unknown_durations = 0
        present_human_tags = set()

        for p in self.folder_path.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() not in DEFAULT_EXTENSIONS:
                continue

            stem_up = p.stem.upper()
            for tag in HUMAN_TAGS:
                if stem_up.endswith(f"_{tag}"):
                    present_human_tags.add(tag)
                    break
            if stem_up.endswith("_INTEGRITY"):
                integrity_count += 1
            is_covert = stem_up.endswith("_COVERT")

            dur = get_duration_seconds(p)
            if dur is None:
                unknown_durations += 1
                continue

            total_seconds += dur
            if is_covert:
                covert_seconds += dur
            if any(stem_up.endswith(f"_{tag}") for tag in HUMAN_TAGS):
                human_seconds += dur

        total_minutes = total_seconds / 60.0
        human_minutes = human_seconds / 60.0
        covert_minutes = covert_seconds / 60.0
        if len(present_human_tags) == 1:
            tag_label = next(iter(present_human_tags)).title()
        else:
            tag_label = "Human-Tagged"

        lines = [
            f"Total video: {total_minutes:.2f} minutes",
            f"{tag_label} video: {human_minutes:.2f} minutes",
            f"Covert video: {covert_minutes:.2f} minutes",
            f"Integrity clips: {integrity_count}",
        ]
        if unknown_durations:
            lines.append(f"Unknown duration clips: {unknown_durations}")
        self.output_label.setText("\n".join(lines))


def main():
    app = QtWidgets.QApplication([])
    win = MainWindow()
    win.show()
    app.exec_()


if __name__ == "__main__":
    main()
