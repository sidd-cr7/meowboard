"""
Windows System Tray Manager for MEOWBOARD.
Manages the notification area icon, right-click menu, quick controls, and background persistence.
"""
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QActionGroup
from PySide6.QtWidgets import QSystemTrayIcon, QMenu

from ..config.settings import (
    INTENSITY_CHANNELS,
    PERSONALITIES,
)
from ..utils.logger import logger


class TrayManager(QObject):
    """
    Encapsulates QSystemTrayIcon and tray menu actions.
    """
    toggle_requested = Signal(bool)
    show_window_requested = Signal()
    intensity_changed = Signal(str)
    personality_changed = Signal(str)
    volume_changed = Signal(int)
    quit_requested = Signal()

    def __init__(
        self,
        active_icon_path: Path,
        inactive_icon_path: Path,
        parent=None,
    ):
        super().__init__(parent)
        self._active_icon_path = active_icon_path
        self._inactive_icon_path = inactive_icon_path

        self._active_icon = QIcon(str(active_icon_path))
        self._inactive_icon = QIcon(str(inactive_icon_path))

        self._tray_icon = QSystemTrayIcon(self._active_icon, parent)
        self._menu = QMenu()

        self._toggle_action: Optional[QAction] = None
        self._personality_actions = {}
        self._intensity_actions = {}
        self._init_menu()

        # Connect double-click / activation
        self._tray_icon.activated.connect(self._on_tray_activated)

    def _init_menu(self):
        """Constructs the system tray context menu."""
        # Open Application
        open_action = QAction("Open MEOWBOARD", self._menu)
        font = open_action.font()
        font.setBold(True)
        open_action.setFont(font)
        open_action.triggered.connect(self.show_window_requested.emit)
        self._menu.addAction(open_action)

        self._menu.addSeparator()

        # Enable / Disable sound toggle
        self._toggle_action = QAction("Meow sounds enabled", self._menu)
        self._toggle_action.setCheckable(True)
        self._toggle_action.setChecked(True)
        self._toggle_action.toggled.connect(self.toggle_requested.emit)
        self._menu.addAction(self._toggle_action)

        self._menu.addSeparator()

        # Personality Submenu
        personality_menu = self._menu.addMenu("Cat Personality")
        p_group = QActionGroup(self)
        p_group.setExclusive(True)
        for p in PERSONALITIES:
            p_action = QAction(p.title(), personality_menu)
            p_action.setCheckable(True)
            p_action.setData(p)
            p_action.triggered.connect(lambda checked, name=p: self.personality_changed.emit(name))
            p_group.addAction(p_action)
            personality_menu.addAction(p_action)
            self._personality_actions[p] = p_action
            if p == PERSONALITIES[0]:
                p_action.setChecked(True)

        # Intensity Submenu
        intensity_menu = self._menu.addMenu("Meow Intensity")
        i_group = QActionGroup(self)
        i_group.setExclusive(True)
        for mode in INTENSITY_CHANNELS:
            channels = INTENSITY_CHANNELS[mode]
            i_action = QAction(f"{mode.title()} ({channels} channels)", intensity_menu)
            i_action.setCheckable(True)
            i_action.setData(mode)
            i_action.triggered.connect(lambda checked, m=mode: self.intensity_changed.emit(m))
            i_group.addAction(i_action)
            intensity_menu.addAction(i_action)
            self._intensity_actions[mode] = i_action
            if mode == "NORMAL":
                i_action.setChecked(True)

        # Quick Volume Submenu
        vol_menu = self._menu.addMenu("Quick Volume")
        vol_levels = [100, 80, 60, 40, 20]
        for v in vol_levels:
            v_action = QAction(f"{v}%", vol_menu)
            v_action.triggered.connect(lambda checked, val=v: self.volume_changed.emit(val))
            vol_menu.addAction(v_action)

        self._menu.addSeparator()

        # Quit Action
        quit_action = QAction("Exit MEOWBOARD", self._menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        self._menu.addAction(quit_action)

        self._tray_icon.setContextMenu(self._menu)
        self._tray_icon.setToolTip("MEOWBOARD 🐈 (Active)")

    def _on_tray_activated(self, reason):
        # Triggered on left click or double click
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window_requested.emit()

    def show(self):
        self._tray_icon.show()

    def hide(self):
        self._tray_icon.hide()

    def set_enabled_state(self, enabled: bool):
        """Updates tray icon, tooltip, and menu checkbox."""
        if self._toggle_action:
            self._toggle_action.blockSignals(True)
            self._toggle_action.setChecked(enabled)
            self._toggle_action.blockSignals(False)

        if enabled:
            self._tray_icon.setIcon(self._active_icon)
            self._tray_icon.setToolTip("MEOWBOARD 🐈 (Purring & Active)")
        else:
            self._tray_icon.setIcon(self._inactive_icon)
            self._tray_icon.setToolTip("MEOWBOARD 🐈 (Muted / Sleeping)")

    def set_personality(self, personality: str):
        a = self._personality_actions.get(personality)
        if a is not None:
            a.setChecked(True)

    def set_intensity(self, mode: str):
        a = self._intensity_actions.get(mode)
        if a is not None:
            a.setChecked(True)

    @staticmethod
    def is_available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    @property
    def menu(self) -> QMenu:
        return self._menu

    def show_message(self, title: str, message: str, msec: int = 2500):
        if self._tray_icon.isVisible():
            self._tray_icon.showMessage(title, message, QSystemTrayIcon.Information, msec)
