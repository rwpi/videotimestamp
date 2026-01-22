import sys, os
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QFileDialog, QMainWindow
from PyQt5.QtCore import Qt, QSettings, QUrl
from PyQt5.QtGui import QPixmap, QDesktopServices
from timestamp import Worker
from autodelete import delete_files
from importtoday import ImportThread
from check_for_updates import check_for_updates
from menubar import setup_menu_bar
from ui_setup import setup_ui

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
        self.check_if_ready_to_process()

    def reset_output_folder(self):
        self.output_folder_path = ""
        self.output_folder_label.setText("Output Folder:")
        self.check_if_ready_to_process()

    def check_if_ready_to_process(self):
        if self.input_files and self.output_folder_path:
            self.process_button.setEnabled(True)
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
        self.status_label.setText("Timestamping complete.")
        self.progress_bar.setValue(100)
        self.process_button.setEnabled(True)
        if self.settings.value('delete_input_files', False, type=bool):
            delete_files(self.input_files)

    def open_folder(self):
        if self.output_folder_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_folder_path))

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
                self.status_label.setText(f"Timestamping file 1/{total_files}")
            else:
                self.status_label.setText("Timestamping file 0/0")
            self.progress_bar.setValue(0)
            self.worker.progressChanged.connect(self.progress_bar.setValue)
            self.worker.progressDetail.connect(self.update_timestamp_status)
            self.worker.finished.connect(self.on_worker_finished)
            self.worker.start()
            self.process_button.setEnabled(False)

    def start_import(self):
        self.import_thread = ImportThread()
        self.import_thread.progress.connect(self.update_progress)
        self.import_thread.finished.connect(self.finish_import)
        self.import_thread.start()
        self.status_label.setText("Importing files...")
        self.progress_bar.setValue(0)
        self.import_thread.finished.connect(self.set_output_folder)
        self.import_thread.finished.connect(self.add_new_files)

    def update_progress(self, value):
        self.status_label.setText(f"Importing files... {value}%")
        self.progress_bar.setValue(value)

    def finish_import(self):
        self.status_label.setText("Import complete.")
        self.progress_bar.setValue(100)

    def update_timestamp_status(self, current, total):
        if total > 0:
            self.status_label.setText(f"Timestamping file {current}/{total}")

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
