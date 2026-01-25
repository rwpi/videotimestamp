import sys, os
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QLabel,
    QFileDialog,
    QMainWindow,
    QDialog,
    QDialogButtonBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QCheckBox,
)
from PyQt5.QtCore import Qt, QSettings, QUrl, QDate, QTimer
from PyQt5.QtGui import QPixmap, QDesktopServices
from timestamp import Worker
from autodelete import delete_files
from importtoday import ImportThread
from check_for_updates import check_for_updates
from menubar import setup_menu_bar
from ui_setup import setup_ui
import showsdcard

class ImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import From SD Card")
        self.setModal(True)
        self.settings = QSettings("VideoTimestamp", "VTS")

        default_base = self._default_destination_base()
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())

        self.destination_path = str(default_base)
        self.destination_label = QLabel()
        self.destination_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._set_destination_display(self.destination_path)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.browse_destination)

        destination_row = QHBoxLayout()
        destination_row.addWidget(self.destination_label)
        destination_row.addWidget(browse_button)

        self.sd_status_dot = QLabel()
        self.sd_status_dot.setFixedSize(10, 10)
        self.sd_status_dot.setStyleSheet("border-radius: 5px; background-color: #d9534f;")
        self.sd_status_text = QLabel("Not Detected")
        status_width = self.sd_status_text.fontMetrics().horizontalAdvance("Not Detected") + 6
        self.sd_status_text.setFixedWidth(status_width)
        self.sd_status_button = QPushButton("Open")
        self.sd_status_button.setEnabled(False)
        self.sd_status_button.clicked.connect(self._open_sd_card_mts)

        sd_status_row = QHBoxLayout()
        sd_status_row.addWidget(self.sd_status_dot)
        sd_status_row.addSpacing(6)
        sd_status_row.addWidget(self.sd_status_text)
        sd_status_row.addWidget(self.sd_status_button)
        sd_status_row.addStretch(1)

        self.skip_duplicates_checkbox = QCheckBox("Avoid Duplicates")
        self.skip_duplicates_checkbox.setChecked(
            self.settings.value("skip_duplicates", True, type=bool)
        )
        self.skip_duplicates_checkbox.toggled.connect(self._on_skip_duplicates_toggled)

        form_layout = QFormLayout()
        form_layout.addRow("SD card status:", sd_status_row)
        form_layout.addRow("Import date:", self.date_edit)
        form_layout.addRow("Destination folder:", destination_row)
        form_layout.addRow("", self.skip_duplicates_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(buttons)
        self.setLayout(layout)

        self.sd_timer = QTimer(self)
        self.sd_timer.setInterval(1000)
        self.sd_timer.timeout.connect(self.update_sd_status)
        self.sd_timer.start()
        self.update_sd_status()

    def _default_destination_base(self):
        if os.name == "nt":
            return os.path.join(os.path.expanduser("~"), "Videos")
        return os.path.join(os.path.expanduser("~"), "Movies")

    def _set_destination_display(self, path):
        base_name = Path(path).name if path else ""
        display_name = base_name or path
        self.destination_label.setText(display_name)
        if path:
            self.destination_label.setToolTip(path)

    def _on_skip_duplicates_toggled(self, checked):
        self.settings.setValue("skip_duplicates", checked)

    def browse_destination(self):
        start_dir = self.destination_path or self._default_destination_base()
        folder = QFileDialog.getExistingDirectory(self, "Select import destination", start_dir)
        if folder:
            self.destination_path = folder
            self._set_destination_display(folder)

    def update_sd_status(self):
        detected = self._has_sd_card()
        if detected:
            self.sd_status_dot.setStyleSheet("border-radius: 5px; background-color: #5cb85c;")
            self.sd_status_text.setText("Detected")
            self.sd_status_button.setEnabled(True)
        else:
            self.sd_status_dot.setStyleSheet("border-radius: 5px; background-color: #d9534f;")
            self.sd_status_text.setText("Not Detected")
            self.sd_status_button.setEnabled(False)

    def _has_sd_card(self):
        if os.name == "nt":
            drives = [f"{chr(letter)}:\\" for letter in range(67, 91)]
        else:
            volumes_path = Path("/Volumes")
            if not volumes_path.is_dir():
                return False
            drives = [str(volume) for volume in volumes_path.iterdir() if volume.is_dir()]

        for drive in drives:
            drive_path = Path(drive)
            if not drive_path.is_dir():
                continue
            for root in ("PRIVATE", "private"):
                stream_path = drive_path / root / "AVCHD" / "BDMV" / "STREAM"
                if stream_path.is_dir():
                    return True
        return False

    def _open_sd_card_mts(self, _link):
        showsdcard.show_sd_card()

    def get_values(self):
        selected_date = self.date_edit.date().toPyDate()
        destination_base = self.destination_path or None
        skip_duplicates = self.skip_duplicates_checkbox.isChecked()
        return selected_date, destination_base, skip_duplicates

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(__file__)

        self.input_files = set()

        self.settings = QSettings('VideoTimestamp', 'VTS')
        self.layout = QVBoxLayout()
        self.copyright_label = QLabel()
        self.copyright_label.setStyleSheet("color: grey; font-size: 10px;")
        self.output_folder_path = ""
    
        self.central_widget = QWidget()
        self.central_widget.setLayout(self.layout)
        self.setCentralWidget(self.central_widget)
        setup_menu_bar(self)
  
        self.setWindowTitle("Video Timestamp")
        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignCenter)
        splashgraphic_path = os.path.join(base_path, 'splashgraphic.png')
        pixmap = QPixmap(splashgraphic_path)
        self.logo_label.setPixmap(pixmap)
        self.layout.addWidget(self.logo_label)      

        setup_ui(self)

        self.check_for_updates()

    def check_for_updates(self):
        text, style = check_for_updates()
        self.version_label.setText(text)
        self.version_label.setStyleSheet(style)

    def launch_video_renamer(self):
        from video_renamer_gui import MainWindow as VideoRenamerWindow
        initial_folder = self.output_folder_path or None
        self.video_renamer_window = VideoRenamerWindow(initial_folder=initial_folder)
        self.video_renamer_window.run_started.connect(self.on_renamer_started)
        self.video_renamer_window.progress_changed.connect(self.update_renamer_progress)
        self.video_renamer_window.run_finished.connect(self.on_renamer_finished)
        self.video_renamer_window.show()
        self.position_video_renamer_window()

    def position_video_renamer_window(self):
        if not hasattr(self, "video_renamer_window") or not self.video_renamer_window:
            return
        screen = QApplication.primaryScreen()
        if not screen:
            return
        screen_geom = screen.availableGeometry()
        main_geom = self.frameGeometry()
        renamer_geom = self.video_renamer_window.frameGeometry()
        margin = 20

        right_x = main_geom.right() + margin
        left_x = main_geom.left() - renamer_geom.width() - margin

        if right_x + renamer_geom.width() <= screen_geom.right():
            x = right_x
        elif left_x >= screen_geom.left():
            x = left_x
        else:
            x = min(max(screen_geom.left(), right_x), screen_geom.right() - renamer_geom.width())

        y = min(
            max(screen_geom.top(), main_geom.top()),
            screen_geom.bottom() - renamer_geom.height(),
        )

        self.video_renamer_window.move(x, y)

    def open_update_link(self, link):
        QDesktopServices.openUrl(QUrl(link))

    def update_output_folder_path(self, path):
        self.output_folder_path = path

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_folder_path))

    def choose_output_folder(self):
        self.output_folder_path = QFileDialog.getExistingDirectory(self, 'Select a folder:')
        if self.output_folder_path:
            folder_name = os.path.basename(self.output_folder_path)
            self.output_folder_label.setText(f"Output Folder: {folder_name}")
            self.check_if_ready_to_process()

    def choose_input_files(self):
        new_input_files, _ = QFileDialog.getOpenFileNames(self, 'Select .MTS files', '', 'MTS Files (*.MTS)')
        if new_input_files:
            self.input_files.update(new_input_files)
            self.input_files_label.setText(f"{len(self.input_files)} Input Files Selected")
            self.input_files_list.clear()
            for file in self.input_files:
                self.input_files_list.addItem(os.path.basename(file)) 
            self.check_if_ready_to_process()
    
    def reset_input_files(self):
        self.input_files = set()
        self.input_files_label.setText("0 Input Files Selected")
        self.input_files_list.clear()
        self.choose_input_files_button.setEnabled(True)
        self.check_if_ready_to_process()

    def reset_output_folder(self):
        self.output_folder_path = ""
        self.output_folder_label.setText("Output Folder:")
        self.choose_button.setEnabled(True)
        self.check_if_ready_to_process()

    def check_if_ready_to_process(self):
        if self.input_files and self.output_folder_path:
            self.process_button.setEnabled(True)
            if self.status_label.text().startswith("Import Complete"):
                self.process_button.setFocus()
        else:
            self.process_button.setEnabled(False)

    def save_settings(self):
        self.settings.setValue('remove_audio', self.remove_audio_action.isChecked())
        self.settings.setValue('use_hwaccel', self.use_hwaccel_action.isChecked())
        self.settings.setValue('manually_adjusted_for_dst', self.manually_adjusted_for_dst_action.isChecked())
        self.settings.setValue('add_hour', self.add_hour_action.isChecked())
        self.settings.setValue('subtract_hour', self.subtract_hour_action.isChecked())
        self.settings.setValue('delete_input_files', self.delete_input_files_action.isChecked())
        if hasattr(self, "date_format_group"):
            selected = self.date_format_group.checkedAction()
            if selected:
                self.settings.setValue('date_format', selected.data())

    def on_worker_finished(self):
        self.timer.stop()
        self.status_label.setText("Timestamping Complete")
        self.progress_bar.setValue(100)
        self.process_button.setEnabled(True)
        if self.settings.value('delete_input_files', False, type=bool):
            delete_files(self._files_within_output_folder(self.input_files))
        self.rename_button.setFocus()

    def open_folder(self):
        if self.output_folder_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_folder_path))

    def _files_within_output_folder(self, paths):
        if not self.output_folder_path:
            return []
        output_root = Path(self.output_folder_path).expanduser().resolve()
        safe_paths = []
        for path in paths:
            try:
                resolved = Path(path).expanduser().resolve()
                resolved.relative_to(output_root)
            except Exception:
                continue
            safe_paths.append(str(resolved))
        return safe_paths

    def main(self):
        if self.input_files:
            self.timer.start(500)
            hwaccel_method = self.hwaccel_method if self.settings.value('use_hwaccel', True, type=bool) else 'libx264'
            remove_audio = self.settings.value('remove_audio', True, type=bool)
            manually_adjusted_for_dst = self.manually_adjusted_for_dst_action.isChecked()
            add_hour = self.settings.value('add_hour', False, type=bool)
            subtract_hour = self.settings.value('subtract_hour', False, type=bool)
            date_format = self.settings.value('date_format', "%m-%d-%Y")
            self.worker = Worker(self.input_files, self.output_folder_path, hwaccel_method, remove_audio, manually_adjusted_for_dst, add_hour, subtract_hour, date_format)
            total_files = len(self.input_files)
            if total_files > 0:
                self.status_label.setText("Timestamping Files")
            else:
                self.status_label.setText("Timestamping Files")
            self.progress_bar.setValue(0)
            self.worker.progressChanged.connect(self.progress_bar.setValue)
            self.worker.progressDetail.connect(self.update_timestamp_status)
            self.worker.finished.connect(self.on_worker_finished)
            self.worker.start()
            self.process_button.setEnabled(False)
            self.progress_bar.setFocus()

    def start_import(self):
        dialog = ImportDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return
        selected_date, destination_base, skip_duplicates = dialog.get_values()
        self.import_thread = ImportThread(
            selected_date=selected_date,
            destination_base=destination_base,
            skip_duplicates=skip_duplicates,
        )
        self.import_thread.progress.connect(self.update_progress)
        self.import_thread.finished.connect(self.finish_import)
        self.import_thread.start()
        self.status_label.setText("Importing Files")
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setValue(0)
        self.import_thread.finished.connect(self.set_output_folder)
        self.import_thread.finished.connect(self.add_new_files)

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def on_renamer_started(self):
        self.status_label.setText("Renaming Files")
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setValue(0)

    def update_renamer_progress(self, value):
        self.progress_bar.setValue(value)

    def on_renamer_finished(self):
        self.status_label.setText("Renaming Complete")
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("%p%")

    def finish_import(self):
        self.status_label.setText("Import Complete")
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("%p%")
        self.process_button.setFocus()
        self.choose_input_files_button.setEnabled(False)
        self.choose_button.setEnabled(False)

    def update_timestamp_status(self, current, total):
        if total > 0:
            self.status_label.setText("Timestamping Files")

    def set_output_folder(self, folder_path):
        self.output_folder_path = folder_path
        folder_name = os.path.basename(self.output_folder_path)
        self.output_folder_label.setText(f"Output Folder: {folder_name}")
        self.check_if_ready_to_process()
        
    def add_new_files(self, folder_path, new_files):
        self.output_folder = folder_path
        self.input_files.update(new_files)
        self.input_files_label.setText(f"{len(self.input_files)} Input Files Selected")
        self.input_files_list.clear()
        for file in self.input_files:
            self.input_files_list.addItem(os.path.basename(file)) 
        self.check_if_ready_to_process()

app = QApplication([])
window = MainWindow()
window.show()
app.exec_()
