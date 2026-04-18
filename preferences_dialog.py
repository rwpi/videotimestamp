from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QWidget,
    QLabel,
    QCheckBox,
    QComboBox,
    QPushButton,
    QDialogButtonBox,
    QButtonGroup,
    QRadioButton,
    QFormLayout,
)
from PyQt5.QtCore import Qt, QSettings


class PreferencesDialog(QDialog):
    DATE_FORMATS = [
        ("MM-DD-YYYY (US)", "%m-%d-%Y"),
        ("DD-MM-YYYY (International)", "%d-%m-%Y"),
        ("Mon-DD-YYYY (Jan, Feb)", "%b-%d-%Y"),
        ("DD-Mon-YYYY (Jan, Feb)", "%d-%b-%Y"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumSize(680, 460)
        self.settings = QSettings("VideoTimestamp", "VTS")

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(208)
        self.sidebar.setFrameShape(QFrame.StyledPanel)
        self.sidebar.setStyleSheet("QListWidget { padding: 8px; } QListWidget::item { padding: 8px 12px; }")
        for section in [
            "Video Processing",
            "Video Renamer",
            "Camera Specific",
            "File Handling",
            "Time Correction",
            "Date Format",
        ]:
            item = QListWidgetItem(section)
            item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self.sidebar.addItem(item)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_video_processing_page())
        self.stack.addWidget(self._build_renamer_page())
        self.stack.addWidget(self._build_camera_settings_page())
        self.stack.addWidget(self._build_file_handling_page())
        self.stack.addWidget(self._build_time_correction_page())
        self.stack.addWidget(self._build_date_format_page())

        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(0)
        content_layout.addWidget(self.sidebar)
        content_layout.addWidget(self.stack, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._save_and_close)
        button_box.rejected.connect(self.reject)

        outer_layout = QVBoxLayout(self)
        outer_layout.addLayout(content_layout)
        outer_layout.addSpacing(8)
        outer_layout.addWidget(button_box)

        self.load_settings()

    def _build_video_processing_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.use_hwaccel_checkbox = QCheckBox("Use Hardware Acceleration")
        self.remove_audio_checkbox = QCheckBox("Remove Audio")

        layout.addWidget(self.use_hwaccel_checkbox)
        layout.addWidget(self.remove_audio_checkbox)
        layout.addStretch(1)
        return page

    def _build_renamer_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.renamer_clip_numbers_checkbox = QCheckBox("Label Clip Number")
        self.renamer_ai_detection_checkbox = QCheckBox("Detect and Tag Humans")
        self.renamer_respect_existing_tags_checkbox = QCheckBox("Respect Existing Tags")
        self.renamer_append_covert_checkbox = QCheckBox("Append _COVERT to LawMate filenames")
        self.renamer_sensitivity_combo = QComboBox()
        self.renamer_sensitivity_combo.addItems(["Low", "Medium", "High"])
        self.renamer_human_tag_combo = QComboBox()
        self.renamer_human_tag_combo.addItems(["HUMAN", "CLAIMANT", "SUBJECT"])

        layout.addWidget(self.renamer_clip_numbers_checkbox)
        layout.addWidget(self.renamer_ai_detection_checkbox)
        layout.addWidget(self.renamer_respect_existing_tags_checkbox)
        layout.addWidget(self.renamer_append_covert_checkbox)

        sensitivity_row = QHBoxLayout()
        sensitivity_row.addWidget(QLabel("Detection Sensitivity"))
        sensitivity_row.addWidget(self.renamer_sensitivity_combo)
        sensitivity_row.addStretch(1)
        layout.addLayout(sensitivity_row)

        human_tag_row = QHBoxLayout()
        human_tag_row.addWidget(QLabel("Tag Human Clips As"))
        human_tag_row.addWidget(self.renamer_human_tag_combo)
        human_tag_row.addStretch(1)
        layout.addLayout(human_tag_row)

        layout.addStretch(1)
        return page

    def _build_camera_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.skip_panasonic_vx3_checkbox = QCheckBox("Skip Timestamp for Panasonic HC-VX3")
        self.skip_lawmate_checkbox = QCheckBox("Skip Timestamp for LawMate Covert Cam")
        self.append_lawmate_checkbox = QCheckBox("Append _COVERT to processed LawMate filenames")

        layout.addWidget(self.skip_panasonic_vx3_checkbox)
        layout.addWidget(self.skip_lawmate_checkbox)
        layout.addWidget(self.append_lawmate_checkbox)
        layout.addStretch(1)
        return page

    def _build_file_handling_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.retain_originals_checkbox = QCheckBox("Retain Originals After Processing")
        self.skip_duplicates_checkbox = QCheckBox("Avoid Duplicates During Import")

        layout.addWidget(self.retain_originals_checkbox)
        layout.addWidget(self.skip_duplicates_checkbox)
        layout.addStretch(1)
        return page

    def _build_time_correction_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.dst_fix_checkbox = QCheckBox("Sony DST Fix")
        self.add_hour_checkbox = QCheckBox("Adjust timestamp +1 hour")
        self.subtract_hour_checkbox = QCheckBox("Adjust timestamp -1 hour")

        layout.addWidget(self.dst_fix_checkbox)
        layout.addWidget(self.add_hour_checkbox)
        layout.addWidget(self.subtract_hour_checkbox)
        layout.addStretch(1)
        return page

    def _build_date_format_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        self.date_format_combo = QComboBox()
        for label, _ in self.DATE_FORMATS:
            self.date_format_combo.addItem(label)

        layout.addWidget(QLabel("Choose your preferred date format:"))
        layout.addWidget(self.date_format_combo)
        layout.addStretch(1)
        return page

    def load_settings(self):
        self.use_hwaccel_checkbox.setChecked(self.settings.value('use_hwaccel', True, type=bool))
        self.remove_audio_checkbox.setChecked(self.settings.value('remove_audio', True, type=bool))
        self.dst_fix_checkbox.setChecked(self.settings.value('manually_adjusted_for_dst', False, type=bool))
        self.add_hour_checkbox.setChecked(self.settings.value('add_hour', False, type=bool))
        self.subtract_hour_checkbox.setChecked(self.settings.value('subtract_hour', False, type=bool))
        self.skip_panasonic_vx3_checkbox.setChecked(self.settings.value('skip_panasonic_vx3_timestamp', False, type=bool))
        self.skip_lawmate_checkbox.setChecked(self.settings.value('skip_lawmate_timestamp', True, type=bool))
        self.append_lawmate_checkbox.setChecked(self.settings.value('append_lawmate_covert_suffix', True, type=bool))
        self.retain_originals_checkbox.setChecked(self.settings.value('retain_originals', False, type=bool))
        self.skip_duplicates_checkbox.setChecked(self.settings.value('skip_duplicates', True, type=bool))
        self.renamer_clip_numbers_checkbox.setChecked(self.settings.value('vrn/clip_numbers', True, type=bool))
        self.renamer_ai_detection_checkbox.setChecked(self.settings.value('vrn/ai_detection', True, type=bool))
        self.renamer_respect_existing_tags_checkbox.setChecked(
            self.settings.value('vrn/respect_existing_tags', True, type=bool)
        )
        self.renamer_append_covert_checkbox.setChecked(self.settings.value('vrn/append_covert', True, type=bool))
        saved_confidence = self.settings.value('vrn/ai_confidence', 55, type=int)
        sensitivity_index = 1
        if saved_confidence <= 45:
            sensitivity_index = 0
        elif saved_confidence >= 65:
            sensitivity_index = 2
        self.renamer_sensitivity_combo.setCurrentIndex(sensitivity_index)
        tag = self.settings.value('vrn/human_tag', 'HUMAN')
        index = self.renamer_human_tag_combo.findText(str(tag).upper())
        if index >= 0:
            self.renamer_human_tag_combo.setCurrentIndex(index)
        current_format = self.settings.value('date_format', "%m-%d-%Y")
        selected_index = 0
        for idx, (_, fmt) in enumerate(self.DATE_FORMATS):
            if fmt == current_format:
                selected_index = idx
                break
        self.date_format_combo.setCurrentIndex(selected_index)

    def _save_and_close(self):
        self.settings.setValue('use_hwaccel', self.use_hwaccel_checkbox.isChecked())
        self.settings.setValue('remove_audio', self.remove_audio_checkbox.isChecked())
        self.settings.setValue('manually_adjusted_for_dst', self.dst_fix_checkbox.isChecked())
        self.settings.setValue('add_hour', self.add_hour_checkbox.isChecked())
        self.settings.setValue('subtract_hour', self.subtract_hour_checkbox.isChecked())
        self.settings.setValue('skip_panasonic_vx3_timestamp', self.skip_panasonic_vx3_checkbox.isChecked())
        self.settings.setValue('skip_lawmate_timestamp', self.skip_lawmate_checkbox.isChecked())
        self.settings.setValue('append_lawmate_covert_suffix', self.append_lawmate_checkbox.isChecked())
        self.settings.setValue('retain_originals', self.retain_originals_checkbox.isChecked())
        self.settings.setValue('skip_duplicates', self.skip_duplicates_checkbox.isChecked())
        self.settings.setValue('vrn/clip_numbers', self.renamer_clip_numbers_checkbox.isChecked())
        self.settings.setValue('vrn/ai_detection', self.renamer_ai_detection_checkbox.isChecked())
        self.settings.setValue('vrn/respect_existing_tags', self.renamer_respect_existing_tags_checkbox.isChecked())
        self.settings.setValue('vrn/append_covert', self.renamer_append_covert_checkbox.isChecked())
        confidence_percent = 55
        sensitivity_index = self.renamer_sensitivity_combo.currentIndex()
        if sensitivity_index == 0:
            confidence_percent = 45
        elif sensitivity_index == 1:
            confidence_percent = 55
        elif sensitivity_index == 2:
            confidence_percent = 65
        self.settings.setValue('vrn/ai_confidence', confidence_percent)
        self.settings.setValue('vrn/human_tag', self.renamer_human_tag_combo.currentText().strip().upper())
        selected_format = self.DATE_FORMATS[self.date_format_combo.currentIndex()][1]
        self.settings.setValue('date_format', selected_format)
        self.settings.sync()
        self.accept()
