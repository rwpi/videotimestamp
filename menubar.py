from PyQt5.QtWidgets import QAction, QActionGroup
import showsdcard

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
    window.delete_input_files_action = QAction("Delete Input Files When Finished", window)
    window.delete_input_files_action.setCheckable(True)
    window.delete_input_files_action.setChecked(window.settings.value('delete_input_files', False, type=bool))
    window.delete_input_files_action.triggered.connect(window.save_settings)
    window.settings_menu.addAction(window.delete_input_files_action)
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
    window.fixes_menu = window.menu_bar.addMenu("Fixes")
    window.manually_adjusted_for_dst_action = QAction("Manually set DST", window)
    window.manually_adjusted_for_dst_action.setCheckable(True)
    window.manually_adjusted_for_dst_action.triggered.connect(window.save_settings)
    window.fixes_menu.addAction(window.manually_adjusted_for_dst_action)
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
    window.tools_menu = window.menu_bar.addMenu("Tools")
    import_today_action = QAction('Import From SD Card...', window)
    import_today_action.triggered.connect(window.start_import)
    window.tools_menu.addAction(import_today_action)
    show_sd_card_action = QAction('Show .MTS Files On SD Card', window)
    show_sd_card_action.triggered.connect(showsdcard.show_sd_card)
    window.tools_menu.addAction(show_sd_card_action)
