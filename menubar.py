from PyQt5.QtWidgets import QAction, QActionGroup

def setup_menu_bar(window):
    window.menu_bar = window.menuBar()
    window.settings_menu = window.menu_bar.addMenu("Settings")
    window.use_hwaccel_action = QAction("Use Hardware Acceleration", window)
    window.use_hwaccel_action.setCheckable(True)
    window.use_hwaccel_action.setChecked(window.settings.value('use_hwaccel', True, type=bool))
    window.use_hwaccel_action.triggered.connect(window.save_settings)
    window.settings_menu.addAction(window.use_hwaccel_action)
    window.remove_audio_action = QAction("Remove Audio", window)
    window.remove_audio_action.setCheckable(True)
    window.remove_audio_action.setChecked(window.settings.value('remove_audio', True, type=bool))
    window.remove_audio_action.triggered.connect(window.save_settings)
    window.settings_menu.addAction(window.remove_audio_action)
    window.camera_specific_menu = window.settings_menu.addMenu("Camera Specific Settings")
    window.skip_panasonic_vx3_timestamp_action = QAction("Skip Timestamp for Panasonic HC-VX3", window)
    window.skip_panasonic_vx3_timestamp_action.setCheckable(True)
    window.skip_panasonic_vx3_timestamp_action.setChecked(
        window.settings.value('skip_panasonic_vx3_timestamp', False, type=bool)
    )
    window.skip_panasonic_vx3_timestamp_action.triggered.connect(window.save_settings)
    window.camera_specific_menu.addAction(window.skip_panasonic_vx3_timestamp_action)
    window.skip_lawmate_timestamp_action = QAction("Skip Timestamp for LawMate Covert Cam", window)
    window.skip_lawmate_timestamp_action.setCheckable(True)
    window.skip_lawmate_timestamp_action.setChecked(
        window.settings.value('skip_lawmate_timestamp', True, type=bool)
    )
    window.skip_lawmate_timestamp_action.triggered.connect(window.save_settings)
    window.camera_specific_menu.addAction(window.skip_lawmate_timestamp_action)
    window.append_lawmate_covert_suffix_action = QAction("Append _COVERT to LawMate Filenames", window)
    window.append_lawmate_covert_suffix_action.setCheckable(True)
    window.append_lawmate_covert_suffix_action.setChecked(
        window.settings.value('append_lawmate_covert_suffix', True, type=bool)
    )
    window.append_lawmate_covert_suffix_action.triggered.connect(window.save_settings)
    window.camera_specific_menu.addAction(window.append_lawmate_covert_suffix_action)
    window.date_format_menu = window.settings_menu.addMenu("Date Format")
    window.date_format_group = QActionGroup(window)
    date_formats = [
        ("MM-DD-YYYY (US)", "%m-%d-%Y"),
        ("DD-MM-YYYY (International)", "%d-%m-%Y"),
        ("Mon-DD-YYYY (Jan, Feb)", "%b-%d-%Y"),
        ("DD-Mon-YYYY (Jan, Feb)", "%d-%b-%Y"),
    ]
    current_format = window.settings.value('date_format', "%m-%d-%Y")
    for label, fmt in date_formats:
        action = QAction(label, window)
        action.setCheckable(True)
        action.setData(fmt)
        if fmt == current_format:
            action.setChecked(True)
        action.triggered.connect(window.save_settings)
        window.date_format_group.addAction(action)
        window.date_format_menu.addAction(action)
    window.fixes_menu = window.settings_menu.addMenu("Time Correction")
    window.manually_adjusted_for_dst_action = QAction("Sony DST Fix", window)
    window.manually_adjusted_for_dst_action.setCheckable(True)
    window.manually_adjusted_for_dst_action.triggered.connect(window.save_settings)
    window.add_hour_action = QAction("Adjust timestamp +1 hour", window)
    window.add_hour_action.setCheckable(True)
    window.add_hour_action.setChecked(window.settings.value('add_hour', False, type=bool))
    window.add_hour_action.triggered.connect(window.save_settings)
    window.fixes_menu.addAction(window.add_hour_action)
    window.subtract_hour_action = QAction("Adjust timestamp -1 hour", window)
    window.subtract_hour_action.setCheckable(True)
    window.subtract_hour_action.setChecked(window.settings.value('subtract_hour', False, type=bool))
    window.subtract_hour_action.triggered.connect(window.save_settings)
    window.fixes_menu.addAction(window.subtract_hour_action)
    window.fixes_menu.addAction(window.manually_adjusted_for_dst_action)
