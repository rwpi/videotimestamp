from PyQt5.QtWidgets import QAction, QActionGroup
import sys

def setup_menu_bar(window):
    window.menu_bar = window.menuBar()

    # Use platform-appropriate menu name
    if sys.platform == "win32":
        window.settings_menu = window.menu_bar.addMenu("Tools")
    else:
        window.settings_menu = window.menu_bar.addMenu("Settings")

    window.preferences_action = QAction("Preferences...", window)
    window.preferences_action.triggered.connect(window.open_preferences)
    window.settings_menu.addAction(window.preferences_action)
