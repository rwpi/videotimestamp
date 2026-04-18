from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QAbstractItemView,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt, QTimer
from datetime import datetime
from hwaccel_filter import filter_hwaccel_methods


class DroppableQueueList(QListWidget):
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
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
        if paths:
            self.owner.add_input_files(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.owner.remove_selected_input_files()
            event.accept()
            return
        super().keyPressEvent(event)


def setup_ui(self):
    content_layout = QHBoxLayout()
    content_layout.setSpacing(16)

    self.left_column = QFrame()
    self.left_column.setFrameShape(QFrame.StyledPanel)
    self.left_column.setMinimumWidth(220)
    self.left_column_layout = QVBoxLayout(self.left_column)
    self.left_column_layout.setSpacing(12)

    self.center_column = QFrame()
    self.center_column.setFrameShape(QFrame.StyledPanel)
    self.center_column_layout = QVBoxLayout(self.center_column)

    content_layout.addWidget(self.left_column, 0)
    content_layout.addWidget(self.center_column, 1)
    self.layout.addLayout(content_layout, 1)

    self.logo_label.setMaximumSize(260, 140)
    self.logo_label.setScaledContents(False)
    if self.logo_label.pixmap() is not None:
        self.logo_label.setPixmap(
            self.logo_label.pixmap().scaled(
                260,
                140,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )
    self.left_column_layout.addWidget(self.logo_label, alignment=Qt.AlignHCenter)

    self.nav_button_container = QWidget()
    self.nav_button_layout = QVBoxLayout(self.nav_button_container)
    self.nav_button_layout.setContentsMargins(0, 0, 0, 0)
    self.nav_button_layout.setSpacing(10)

    self.workflow_label = QLabel("Workflow")
    self.workflow_label.setStyleSheet(
        "color: #8d8d8d; font-size: 10px; font-weight: 600; letter-spacing: 0.08em;"
    )
    self.nav_button_layout.addWidget(self.workflow_label)

    self.import_button = QPushButton("Import Files")
    self.import_button.setCheckable(True)
    self.import_button.setFocusPolicy(Qt.NoFocus)
    self.import_button.clicked.connect(self.start_import)
    self.nav_button_layout.addWidget(self.import_button)

    self.process_button = QPushButton("Process Video")
    self.process_button.setCheckable(True)
    self.process_button.setFocusPolicy(Qt.NoFocus)
    self.process_button.clicked.connect(self.show_timestamp_panel)
    self.nav_button_layout.addWidget(self.process_button)

    self.tools_label = QLabel("Tools")
    self.tools_label.setStyleSheet(
        "color: #8d8d8d; font-size: 10px; font-weight: 600; letter-spacing: 0.08em; padding-top: 10px;"
    )
    self.nav_button_layout.addWidget(self.tools_label)

    self.rename_button = QPushButton("Rename Files")
    self.rename_button.setCheckable(True)
    self.rename_button.setFocusPolicy(Qt.NoFocus)
    self.rename_button.clicked.connect(self.launch_video_renamer)
    self.nav_button_layout.addWidget(self.rename_button)

    self.total_counter_button = QPushButton("Count Video")
    self.total_counter_button.setCheckable(True)
    self.total_counter_button.setFocusPolicy(Qt.NoFocus)
    self.total_counter_button.clicked.connect(self.launch_video_minutes_counter)
    self.nav_button_layout.addWidget(self.total_counter_button)

    self.merge_button = QPushButton("Merge Clips")
    self.merge_button.setCheckable(True)
    self.merge_button.setFocusPolicy(Qt.NoFocus)
    self.merge_button.clicked.connect(self.launch_merge_clips)
    self.nav_button_layout.addWidget(self.merge_button)

    self.nav_button_container.setStyleSheet(
        "QPushButton {"
        " min-height: 46px;"
        " padding: 0 16px;"
        " text-align: left;"
        " font-size: 15px;"
        " font-weight: 600;"
        " border: 1px solid #3a3a3a;"
        " border-radius: 10px;"
        " background: #303030;"
        " color: #d7d7d7;"
        "}"
        "QPushButton:hover {"
        " background: #373737;"
        " border-color: #4a4a4a;"
        "}"
        "QPushButton:checked {"
        " border: 2px solid #0078d4;"
        " background: #3a3a3a;"
        " color: white;"
        "}"
    )
    self.left_column_layout.addWidget(self.nav_button_container)

    self.left_column_layout.addStretch(1)

    self.module_stack = QStackedWidget()
    self.module_placeholder = QWidget()
    self.module_placeholder_layout = QVBoxLayout(self.module_placeholder)
    self.module_placeholder_layout.setContentsMargins(24, 24, 24, 24)
    self.module_placeholder_layout.setSpacing(12)

    self.module_placeholder_title = QLabel("Select a tool")
    self.module_placeholder_title.setAlignment(Qt.AlignCenter)
    self.module_placeholder_title.setStyleSheet("font-size: 16px; font-weight: 600;")
    self.module_placeholder_layout.addWidget(self.module_placeholder_title)

    self.module_placeholder_text = QLabel(
        "Use the tabs in the left column to switch tools."
    )
    self.module_placeholder_text.setAlignment(Qt.AlignCenter)
    self.module_placeholder_text.setWordWrap(True)
    self.module_placeholder_text.setStyleSheet("color: grey; font-size: 10px;")
    self.module_placeholder_layout.addWidget(self.module_placeholder_text)
    self.module_placeholder_layout.addStretch(1)

    self.module_stack.addWidget(self.module_placeholder)
    self.center_column_layout.addWidget(self.module_stack, 1)
    
    self.queue_panel = QFrame()
    self.queue_panel.setFrameShape(QFrame.StyledPanel)
    self.queue_panel_layout = QVBoxLayout(self.queue_panel)
    self.queue_panel_layout.setContentsMargins(12, 12, 12, 12)
    self.queue_panel_layout.setSpacing(10)

    self.file_queue_title = QLabel("File Queue")
    self.file_queue_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    self.file_queue_title.setStyleSheet("font-size: 13px; font-weight: 600;")
    self.queue_panel_layout.addWidget(self.file_queue_title)

    self.input_files_label = QLabel("0 Input Files Selected")
    self.input_files_label.setStyleSheet("color: grey; font-size: 10px;")
    self.add_input_files_label = QLabel('<a href="#">Add</a>')
    self.add_input_files_label.setStyleSheet("color: blue; font-size: 10px;")
    self.add_input_files_label.linkActivated.connect(self.choose_input_files)
    self.remove_input_files_label = QLabel('<a href="#">Remove</a>')
    self.remove_input_files_label.setStyleSheet("color: blue; font-size: 10px;")
    self.remove_input_files_label.linkActivated.connect(self.remove_selected_input_files)
    self.reset_input_files_label = QLabel('<a href="#">Reset</a>')
    self.reset_input_files_label.setStyleSheet("color: blue; font-size: 10px;")
    self.reset_input_files_label.linkActivated.connect(self.reset_input_files)
    self.input_files_layout = QHBoxLayout()
    self.input_files_layout.addWidget(self.input_files_label)
    self.input_files_layout.addStretch(1)
    self.input_files_layout.addWidget(self.add_input_files_label)
    self.input_files_layout.addWidget(self.remove_input_files_label)
    self.input_files_layout.addWidget(self.reset_input_files_label)
    self.queue_panel_layout.addLayout(self.input_files_layout)

    self.input_files_list = DroppableQueueList(self)
    self.input_files_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
    self.input_files_list.setStyleSheet(
        "QListWidget {"
        " border: 1px dashed #4a4a4a;"
        "}"
    )
    self.input_files_list.setToolTip("Drag and drop video files here")
    self.queue_panel_layout.addWidget(self.input_files_list, 1)

    self.output_folder_title = QLabel("Output Folder")
    self.output_folder_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    self.output_folder_title.setStyleSheet("font-size: 13px; font-weight: 600;")
    self.queue_panel_layout.addWidget(self.output_folder_title)

    self.output_folder_label = QLabel("Output Folder:")
    self.output_folder_label.setStyleSheet("color: grey; font-size: 10px;")
    self.output_folder_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    self.output_folder_label.linkActivated.connect(self.open_folder)
    self.change_output_folder_label = QLabel('<a href="#">Set</a>')
    self.change_output_folder_label.setStyleSheet("color: blue; font-size: 10px;")
    self.change_output_folder_label.linkActivated.connect(self.choose_output_folder)

    self.output_folder_layout = QHBoxLayout()
    self.output_folder_layout.addWidget(self.output_folder_label)
    self.output_folder_layout.addStretch(1)

    self.output_folder_layout.addWidget(self.change_output_folder_label)

    self.queue_panel_layout.addLayout(self.output_folder_layout)

    self.hwaccel_method = filter_hwaccel_methods()

    self.status_label = QLabel("Idle")
    self.status_label.setStyleSheet("color: grey; font-size: 10px;")
    self.status_label.setAlignment(Qt.AlignCenter)
    self.layout.addWidget(self.status_label)

    self.progress_bar = QProgressBar()
    self.progress_bar.setRange(0, 100)
    self.progress_bar.setValue(0)
    self.progress_bar.setTextVisible(True)
    self.progress_bar.setStyleSheet(
        "QProgressBar {"
        " border: 1px solid #4a4a4a;"
        " border-radius: 4px;"
        " text-align: center;"
        " color: #d0d0d0;"
        " background-color: #2b2b2b;"
        "}"
        "QProgressBar::chunk {"
        " background-color: #2ea8ff;"
        "}"
    )
    self.layout.addWidget(self.progress_bar)

    self.timer = QTimer()

    current_year = datetime.now().year
    self.copyright_label.setText(f"© {current_year} Robert Webber | GPL-3.0")
    self.copyright_label.setAlignment(Qt.AlignCenter)

    self.link_label = QLabel()
    self.link_label.setText('<a href="https://www.videotimestamp.com">www.videotimestamp.com</a>')
    self.link_label.setStyleSheet("color: grey; font-size: 10px;")
    self.link_label.setOpenExternalLinks(True)
    self.link_label.setAlignment(Qt.AlignCenter)

    self.version_label = QLabel()
    self.version_label.setStyleSheet("color: grey; font-size: 10px;")
    self.version_label.setAlignment(Qt.AlignCenter)

    self.footer_layout = QHBoxLayout()
    self.footer_layout.addStretch(1)
    self.footer_layout.addWidget(self.version_label)
    self.footer_layout.addSpacing(24)
    self.footer_layout.addWidget(self.copyright_label)
    self.footer_layout.addSpacing(24)
    self.footer_layout.addWidget(self.link_label)
    self.footer_layout.addStretch(1)
    self.layout.addLayout(self.footer_layout)
