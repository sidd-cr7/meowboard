"""
Main window for MEOWBOARD: a minimal dark dashboard whose every control drives the real backend.
"""
from pathlib import Path
import time
from typing import List, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QObject, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..config.settings import AppConfig, INTENSITY_CHANNELS, PERSONALITIES
from ..core.audio_engine import AudioEngine
from ..core.keyboard_listener import KeyboardListener
from ..core.pitch_mapper import KeyProfile
from ..utils.autostart import is_autostart_enabled, set_autostart
from ..utils.config_manager import ConfigManager
from ..utils.logger import logger
from .icon_generator import ensure_app_icons
from .styles import DARK_THEME_QSS
from .tray_manager import TrayManager
from .widgets import (
    BAD, GOOD, MUTED, OFF, WARN, ACCENT,
    KeyboardVisualizer, PulseDot, SegmentedControl, ToggleSwitch,
)

PERSONALITY_BLURB = {
    "NORMAL CAT": "Natural",
    "KITTEN": "Soft chirps",
    "ANGRY CAT": "Raspy",
    "DEEP CAT": "Low & warm",
}
PERSONALITY_LABEL = {
    "NORMAL CAT": "Normal Cat",
    "KITTEN": "Kitten",
    "ANGRY CAT": "Angry Cat",
    "DEEP CAT": "Deep Cat",
}
INTENSITY_LABEL = {"CHILL": "Chill", "NORMAL": "Normal", "CHAOS": "Chaos"}

ACTIVITY_HOLD_S = 0.35   # how long after a meow the UI says "Meowing"


class GuiSignalBridge(QObject):
    """Safely passes events from the audio worker thread to the Qt GUI thread."""
    key_played = Signal(object)


def _card() -> QFrame:
    f = QFrame()
    f.setProperty("class", "Card")
    return f


def _label(text: str, cls: str) -> QLabel:
    l = QLabel(text)
    l.setProperty("class", cls)
    return l


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: AppConfig,
        config_manager: ConfigManager,
        audio_engine: AudioEngine,
        keyboard_listener: KeyboardListener,
        icons_dir: Path,
    ):
        super().__init__()
        self._config = config
        self._config_manager = config_manager
        self._audio_engine = audio_engine
        self._keyboard_listener = keyboard_listener
        self._icons_dir = icons_dir

        self._total_meows = 0
        self._recent: List[float] = []
        self._last_meow_t = 0.0
        self._last_key_name = "—"
        self._is_quitting = False
        self._fade_done = False

        self._icon_paths = ensure_app_icons(self._icons_dir)
        self.setWindowIcon(QIcon(str(self._icon_paths["app_png"])))

        # worker thread -> GUI thread
        self._signal_bridge = GuiSignalBridge()
        self._signal_bridge.key_played.connect(self._on_key_played_gui_thread)
        self._audio_engine._on_key_played = self._on_key_played_worker_thread

        # debounced persistence (slider drags would otherwise write the file on every tick)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save_config_now)

        # tray
        self._tray_manager = TrayManager(
            active_icon_path=self._icon_paths["tray_active"],
            inactive_icon_path=self._icon_paths["tray_inactive"],
            parent=self,
        )
        self._tray_manager.toggle_requested.connect(self._set_enabled)
        self._tray_manager.show_window_requested.connect(self._restore_window)
        self._tray_manager.intensity_changed.connect(self._set_intensity_mode)
        self._tray_manager.personality_changed.connect(self._set_cat_personality)
        self._tray_manager.volume_changed.connect(self._set_volume_val)
        self._tray_manager.quit_requested.connect(self._quit_application)
        self._tray_manager.show()

        self.setWindowTitle("MEOWBOARD")
        self.setMinimumSize(780, 740)
        self.resize(820, 780)
        self.setStyleSheet(DARK_THEME_QSS)
        self._build_ui()
        self._apply_initial_state()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(100)
        self._tick_timer.timeout.connect(self._refresh_live_status)
        self._tick_timer.start()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = QWidget(self)
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 22, 24, 18)
        outer.setSpacing(14)

        # --- header: brand + big ON/OFF
        header = QHBoxLayout()
        header.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(self._icon_paths["app_png"])).scaled(
            48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header.addWidget(logo)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand_box.addWidget(_label("MEOWBOARD", "Brand"))
        brand_box.addWidget(_label("Every keystroke gets a meow", "Tagline"))
        header.addLayout(brand_box)
        header.addStretch()
        sw_box = QVBoxLayout()
        sw_box.setSpacing(4)
        self._toggle = ToggleSwitch(self._config.enabled)
        self._toggle.setToolTip("Turn all meow sounds on or off")
        self._toggle.toggled.connect(self._set_enabled)
        sw_box.addWidget(self._toggle, 0, Qt.AlignRight)
        header.addLayout(sw_box)
        outer.addLayout(header)

        # --- activity + live stats
        act = _card()
        al = QHBoxLayout(act)
        al.setContentsMargins(20, 14, 20, 14)
        al.setSpacing(12)
        self._dot = PulseDot(GOOD)
        al.addWidget(self._dot)
        text_box = QVBoxLayout()
        text_box.setSpacing(0)
        self._activity_label = _label("Listening", "Activity")
        self._activity_sub = _label("", "Muted")
        text_box.addWidget(self._activity_label)
        text_box.addWidget(self._activity_sub)
        al.addLayout(text_box, 1)
        self._stat_key = self._stat(al, "LAST KEY", "—")
        self._stat_speed = self._stat(al, "SPEED", "0.0 /s")
        self._stat_channels = self._stat(al, "CHANNELS", "0 / 12")
        self._stat_total = self._stat(al, "MEOWS", "0")
        outer.addWidget(act)

        # --- keyboard visualisation
        vis = _card()
        vl = QVBoxLayout(vis)
        vl.setContentsMargins(18, 14, 18, 10)
        vl.setSpacing(6)
        vh = QHBoxLayout()
        vh.addWidget(_label("PITCH MAP", "Section"))
        vh.addStretch()
        vh.addWidget(_label("Each key's colour is its pitch for the selected cat", "Muted"))
        vl.addLayout(vh)
        self._keyboard_visualizer = KeyboardVisualizer()
        vl.addWidget(self._keyboard_visualizer)
        outer.addWidget(vis, 1)

        # --- personality
        pc = _card()
        pl = QVBoxLayout(pc)
        pl.setContentsMargins(18, 14, 18, 16)
        pl.setSpacing(10)
        pl.addWidget(_label("CAT PERSONALITY", "Section"))
        self._personality = SegmentedControl(
            [(p, PERSONALITY_LABEL[p], PERSONALITY_BLURB[p]) for p in PERSONALITIES],
            current=self._config.personality)
        self._personality.selected.connect(self._set_cat_personality)
        pl.addWidget(self._personality)
        outer.addWidget(pc)

        # --- intensity
        ic = _card()
        il = QVBoxLayout(ic)
        il.setContentsMargins(18, 14, 18, 16)
        il.setSpacing(10)
        il.addWidget(_label("MEOW INTENSITY", "Section"))
        self._intensity = SegmentedControl(
            [(m, INTENSITY_LABEL[m], f"{n} channels") for m, n in INTENSITY_CHANNELS.items()],
            current=self._config.intensity)
        self._intensity.selected.connect(self._set_intensity_mode)
        il.addWidget(self._intensity)
        outer.addWidget(ic)

        # --- volume + test
        vc = _card()
        vcl = QHBoxLayout(vc)
        vcl.setContentsMargins(18, 14, 18, 14)
        vcl.setSpacing(16)
        vol_box = QVBoxLayout()
        vol_box.setSpacing(6)
        vrow = QHBoxLayout()
        vrow.addWidget(_label("MASTER VOLUME", "Section"))
        vrow.addStretch()
        self._vol_label = _label(f"{self._config.volume}%", "Value")
        vrow.addWidget(self._vol_label)
        vol_box.addLayout(vrow)
        self._volume_slider = QSlider(Qt.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(self._config.volume)
        self._volume_slider.valueChanged.connect(self._on_volume_slider_changed)
        vol_box.addWidget(self._volume_slider)
        vcl.addLayout(vol_box, 1)
        self._test_btn = QPushButton("Test Meow")
        self._test_btn.setProperty("class", "Primary")
        self._test_btn.setCursor(Qt.PointingHandCursor)
        self._test_btn.clicked.connect(self._on_test_meow)
        vcl.addWidget(self._test_btn)
        outer.addWidget(vc)

        # --- footer: audio device + prefs
        foot = QHBoxLayout()
        foot.setContentsMargins(4, 0, 4, 0)
        foot.setSpacing(10)
        self._device_dot = PulseDot(GOOD, size=10)
        foot.addWidget(self._device_dot)
        self._device_label = _label("", "Muted")
        foot.addWidget(self._device_label)
        self._retry_btn = QPushButton("Retry audio")
        self._retry_btn.setProperty("class", "Ghost")
        self._retry_btn.setCursor(Qt.PointingHandCursor)
        self._retry_btn.clicked.connect(self._audio_engine.restart_audio)
        self._retry_btn.hide()
        foot.addWidget(self._retry_btn)
        foot.addStretch()
        self._autostart_cb = QCheckBox("Start with Windows")
        self._autostart_cb.setChecked(is_autostart_enabled())
        self._autostart_cb.toggled.connect(self._on_autostart_toggled)
        foot.addWidget(self._autostart_cb)
        outer.addLayout(foot)

    def _stat(self, layout, caption: str, value: str) -> QLabel:
        box = QVBoxLayout()
        box.setSpacing(0)
        v = _label(value, "Stat")
        v.setMinimumWidth(78)
        v.setAlignment(Qt.AlignRight)
        c = _label(caption, "StatCaption")
        c.setAlignment(Qt.AlignRight)
        box.addWidget(v)
        box.addWidget(c)
        layout.addLayout(box)
        return v

    def _apply_initial_state(self):
        # push saved settings into the real backend (main.py only passes volume/intensity/enabled)
        self._audio_engine.set_personality(self._config.personality)
        self._audio_engine.set_intensity(self._config.intensity)
        self._audio_engine.set_volume(self._config.volume)
        self._audio_engine.set_enabled(self._config.enabled)
        self._tray_manager.set_enabled_state(self._config.enabled)
        self._tray_manager.set_personality(self._config.personality)
        self._tray_manager.set_intensity(self._config.intensity)
        self._keyboard_visualizer.set_mapping(self._audio_engine.pitch_mapper, self._config.personality)
        self._refresh_live_status()

    # ------------------------------------------------------------------ live status

    def _on_key_played_worker_thread(self, profile: KeyProfile):
        self._signal_bridge.key_played.emit(profile)

    def _on_key_played_gui_thread(self, profile: KeyProfile):
        now = time.perf_counter()
        self._total_meows += 1
        self._recent.append(now)
        self._last_meow_t = now
        self._last_key_name = profile.name
        self._keyboard_visualizer.trigger_key_visual(profile)
        self._dot.pulse()
        self._refresh_live_status()

    def _refresh_live_status(self):
        now = time.perf_counter()
        self._recent = [t for t in self._recent if now - t < 1.5]
        info = self._audio_engine.device_info()
        enabled = self._config.enabled

        if not enabled:
            state, color, sub = "Muted", OFF, "Toggle ON to hear meows again"
        elif not info["healthy"]:
            state, color, sub = "Audio problem", BAD, "No sound until the audio device recovers"
        elif not self._keyboard_listener.is_active:
            state, color, sub = "Keyboard listener stopped", WARN, "Restart MEOWBOARD to resume"
        elif now - self._last_meow_t < ACTIVITY_HOLD_S:
            state, color, sub = "Meowing", ACCENT, f"{self._last_key_name} key"
        else:
            state, color, sub = "Listening", GOOD, "Type anywhere in Windows"
        self._activity_label.setText(state)
        self._activity_sub.setText(sub)
        self._dot.set_color(color)

        self._stat_key.setText(self._last_key_name)
        self._stat_speed.setText(f"{len(self._recent) / 1.5:.1f} /s")
        self._stat_channels.setText(f"{self._audio_engine.active_channels} / {info['limit']}")
        self._stat_total.setText(f"{self._total_meows:,}")

        if info["healthy"]:
            self._device_dot.set_color(GOOD)
            self._device_label.setText(
                f"Audio ready  ·  default output  ·  {info['freq'] / 1000:.1f} kHz  ·  {info['buffer_ms']} ms buffer")
            self._retry_btn.hide()
        else:
            self._device_dot.set_color(BAD)
            self._device_label.setText(f"Audio unavailable  ·  {info['error'] or 'device not initialised'}")
            self._retry_btn.show()

    # ------------------------------------------------------------------ actions

    def _set_enabled(self, enabled: bool):
        """ON/OFF from the switch or the tray. OFF silences everything playing immediately."""
        enabled = bool(enabled)
        self._config.enabled = enabled
        self._audio_engine.set_enabled(enabled)      # stop_all() when disabling
        self._toggle.set_checked_silently(enabled)
        self._tray_manager.set_enabled_state(enabled)
        self._save_soon()
        self._refresh_live_status()

    def _set_cat_personality(self, personality: str):
        if personality not in PERSONALITIES:
            return
        self._config.personality = personality
        self._audio_engine.set_personality(personality)
        self._personality.set_current(personality)
        self._tray_manager.set_personality(personality)
        self._keyboard_visualizer.set_mapping(self._audio_engine.pitch_mapper, personality)
        self._save_soon()

    def _set_intensity_mode(self, mode: str):
        if mode not in INTENSITY_CHANNELS:
            return
        self._config.intensity = mode
        self._audio_engine.set_intensity(mode)
        self._intensity.set_current(mode)
        self._tray_manager.set_intensity(mode)
        self._save_soon()

    def _on_volume_slider_changed(self, value: int):
        self._config.volume = value
        self._vol_label.setText(f"{value}%")
        self._audio_engine.set_volume(value)
        self._save_soon()

    def _set_volume_val(self, value: int):
        self._volume_slider.setValue(value)

    def _on_test_meow(self):
        if not self._config.enabled:
            self._set_enabled(True)       # a test only makes sense when audible
        self._audio_engine.trigger_test_meow()

    def _on_autostart_toggled(self, checked: bool):
        self._config.start_with_windows = checked
        set_autostart(checked)
        self._save_soon()

    def _save_soon(self):
        self._save_timer.start()

    def _save_config_now(self):
        self._config_manager.save(self._config)

    # ------------------------------------------------------------------ window / tray behaviour

    def _restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fade_done:                      # gentle fade-in on first show
            self._fade_done = True
            self.setWindowOpacity(0.0)
            self._fade = QPropertyAnimation(self, b"windowOpacity", self)
            self._fade.setDuration(260)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.setEasingCurve(QEasingCurve.OutCubic)
            self._fade.start()

    def changeEvent(self, event):
        """Minimising sends the window to the tray; MEOWBOARD keeps running."""
        if event.type() == event.Type.WindowStateChange and self.isMinimized() and self._tray_ok():
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def _tray_ok(self) -> bool:
        return self._tray_manager.is_available()

    def closeEvent(self, event):
        """Closing the window hides it to the tray (if one exists); use tray > Exit to quit."""
        if not self._is_quitting and self._tray_ok():
            event.ignore()
            self.hide()
            self._tray_manager.show_message("MEOWBOARD", "Still running in the tray. Right-click the icon to exit.", 2000)
        else:
            self._cleanup_and_exit()
            event.accept()

    def _quit_application(self):
        self._is_quitting = True
        self._cleanup_and_exit()
        QApplication.quit()

    def _cleanup_and_exit(self):
        logger.info("Cleaning up MEOWBOARD resources...")
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._save_config_now()
        self._tick_timer.stop()
        self._keyboard_listener.stop()
        self._audio_engine.shutdown()
        self._tray_manager.hide()
