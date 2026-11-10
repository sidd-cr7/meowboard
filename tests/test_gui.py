"""GUI tests (offscreen): every control must drive the real backend."""
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from meowboard.config.settings import AppConfig, INTENSITY_CHANNELS, PERSONALITIES
from meowboard.core.audio_engine import AudioEngine
from meowboard.core.keyboard_listener import KeyboardListener
from meowboard.core.sound_manager import SoundManager
from meowboard.gui.main_window import MainWindow
from meowboard.gui.widgets import pitch_color
from meowboard.utils.config_manager import ConfigManager

ROOT = Path(__file__).resolve().parent.parent
SOUNDS = ROOT / "meowboard" / "assets" / "sounds"
ICONS = ROOT / "meowboard" / "assets" / "icons"
SHOTS = os.environ.get("MEOW_SHOT_DIR")


def wait(ms):
    # (QTest.qWait holds the GIL in PySide6 and starves background threads; sleep instead)
    end = time.time() + ms / 1000
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.004)


def wait_for(cond, timeout_ms=3000):
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture(scope="module")
def sound_manager():
    return SoundManager(assets_dir=SOUNDS)


@pytest.fixture
def env(qapp, sound_manager, tmp_path):
    cfg_mgr = ConfigManager(tmp_path / "settings.json")
    cfg = AppConfig(enabled=True, volume=60, intensity="NORMAL", personality="NORMAL CAT")
    engine = AudioEngine(sound_manager=sound_manager, intensity=cfg.intensity, volume=cfg.volume, enabled=True)
    listener = KeyboardListener(on_key_down=engine.trigger_key, ignore_injected=False)
    listener.start()
    win = MainWindow(cfg, cfg_mgr, engine, listener, ICONS)
    win._autostart_cb.blockSignals(True)           # never touch the real Run registry key in tests
    win._tray_manager.is_available = lambda: True  # offscreen has no tray; behave as if it did
    win.show()
    wait(50)
    yield win, engine, cfg, cfg_mgr, listener
    win._is_quitting = True
    win._tick_timer.stop()
    listener.stop()
    engine.shutdown()
    win._tray_manager.hide()
    win.close()
    win.deleteLater()


def click_segment(ctrl, index):
    x, y = ctrl._cell_xy(index)
    c = ctrl._cell_rect(x, y).center().toPoint()
    QTest.mouseClick(ctrl, Qt.LeftButton, Qt.NoModifier, c)


def long_sound():
    import numpy as np, pygame
    n = 44100 * 3
    mono = (np.sin(2 * np.pi * 440 * np.arange(n) / 44100) * 6000).astype(np.int16)
    return pygame.mixer.Sound(buffer=np.column_stack((mono, mono)).tobytes())


def test_initial_state_reflects_config_and_backend(env):
    win, engine, cfg, *_ = env
    assert win._toggle.isChecked() and engine.is_enabled
    assert win._volume_slider.value() == 60 and win._vol_label.text() == "60%"
    assert win._personality.current() == "NORMAL CAT"
    assert win._intensity.current() == "NORMAL"
    assert win._activity_label.text() == "Listening"
    assert "Audio ready" in win._device_label.text()
    assert not win._retry_btn.isVisible()
    assert win.windowTitle() == "MEOWBOARD"


def test_off_switch_immediately_stops_playing_sounds(env):
    win, engine, cfg, *_ = env
    snd = long_sound()
    for _ in range(8):
        engine.trigger_sound(snd, 0.4)
    assert wait_for(lambda: engine.active_channels > 0)
    t0 = time.perf_counter()
    QTest.mouseClick(win._toggle, Qt.LeftButton)           # real click on the big switch
    ms = (time.perf_counter() - t0) * 1000
    print(f"switch OFF -> silence in {ms:.1f} ms")
    assert not engine.is_enabled and cfg.enabled is False
    assert engine.active_channels == 0 and engine.pending_events == 0
    assert ms < 250
    assert win._activity_label.text() == "Muted"
    assert not win._tray_manager._toggle_action.isChecked()
    # keys while OFF make no sound
    wait(150)                                      # let already-queued GUI signals drain
    before = win._total_meows
    engine.trigger_key(0x41)
    wait(150)
    assert win._total_meows == before and engine.active_channels == 0
    # and back ON
    QTest.mouseClick(win._toggle, Qt.LeftButton)
    assert engine.is_enabled and win._tray_manager._toggle_action.isChecked()
    engine.trigger_key(0x41)
    assert wait_for(lambda: win._total_meows == before + 1)


def test_keyboard_space_toggles_switch(env):
    win, engine, *_ = env
    win._toggle.setFocus()
    QTest.keyClick(win._toggle, Qt.Key_Space)
    assert not engine.is_enabled
    QTest.keyClick(win._toggle, Qt.Key_Space)
    assert engine.is_enabled


def test_volume_slider_drives_engine_and_label(env):
    win, engine, cfg, *_ = env
    win._volume_slider.setValue(20)
    assert engine._volume == 20 and cfg.volume == 20 and win._vol_label.text() == "20%"
    win._volume_slider.setValue(100)
    assert engine._volume == 100
    win._volume_slider.setValue(0)
    assert engine._volume == 0


@pytest.mark.parametrize("index,mode", [(0, "CHILL"), (2, "CHAOS"), (1, "NORMAL")])
def test_intensity_selector_sets_channel_limit(env, index, mode):
    win, engine, cfg, *_ = env
    click_segment(win._intensity, index)
    assert win._intensity.current() == mode and engine._intensity == mode and cfg.intensity == mode
    assert win._tray_manager._intensity_actions[mode].isChecked()
    snd = long_sound()
    for _ in range(INTENSITY_CHANNELS[mode] * 2):
        engine.trigger_sound(snd, 0.3)
        wait(5)
    wait(150)
    assert engine.active_channels == INTENSITY_CHANNELS[mode]
    assert win._stat_channels.text() == f"{INTENSITY_CHANNELS[mode]} / {INTENSITY_CHANNELS[mode]}"


@pytest.mark.parametrize("index", range(4))
def test_personality_selector_switches_sound_set_and_pitch_map(env, index):
    win, engine, cfg, *_ = env
    name = PERSONALITIES[index]
    if index == 0:
        click_segment(win._personality, 1)         # make sure we actually change
    click_segment(win._personality, index)
    assert cfg.personality == name
    assert engine._sound_manager.current_personality == name
    assert win._keyboard_visualizer._personality == name
    assert win._tray_manager._personality_actions[name].isChecked()
    engine.trigger_key(0x41)
    assert wait_for(lambda: win._last_key_name == "A")


def test_test_meow_button_plays_through_engine(env):
    win, *_ = env
    before = win._total_meows
    QTest.mouseClick(win._test_btn, Qt.LeftButton)
    assert wait_for(lambda: win._total_meows == before + 1)
    assert win._activity_label.text() == "Meowing"


def test_test_meow_while_off_turns_sound_on(env):
    win, engine, *_ = env
    win._toggle.click()
    assert not engine.is_enabled
    QTest.mouseClick(win._test_btn, Qt.LeftButton)
    assert engine.is_enabled and win._toggle.isChecked()


def test_activity_indicator_follows_real_keys_and_returns_to_listening(env):
    win, engine, *_ = env
    for vk in (0x48, 0x49):
        engine.trigger_key(vk)
        wait(20)
    assert wait_for(lambda: win._last_key_name == "I")
    win._refresh_live_status()
    assert win._activity_label.text() == "Meowing"
    assert win._stat_key.text() == "I"
    assert wait_for(lambda: win._activity_label.text() == "Listening", 1500)
    assert float(win._stat_speed.text().split()[0]) >= 0


def test_audio_device_status_and_retry(env):
    win, engine, *_ = env
    engine._device_healthy = False
    engine._last_error = "Audio init failed: boom"
    win._refresh_live_status()
    assert "Audio unavailable" in win._device_label.text() and "boom" in win._device_label.text()
    assert not win._retry_btn.isHidden()
    assert win._activity_label.text() == "Audio problem"
    QTest.mouseClick(win._retry_btn, Qt.LeftButton)
    assert wait_for(lambda: engine.is_healthy, 25000)
    win._refresh_live_status()
    assert "Audio ready" in win._device_label.text() and win._retry_btn.isHidden()
    engine.trigger_key(0x41)
    assert wait_for(lambda: win._last_key_name == "A")


def test_tray_menu_has_required_actions_and_they_work(env, monkeypatch):
    win, engine, *_ = env
    menu = win._tray_manager.menu
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("Open" in t for t in texts) and any("Exit" in t for t in texts)
    assert any("enabled" in t.lower() for t in texts)

    win.hide()
    next(a for a in menu.actions() if "Open" in a.text()).trigger()
    assert win.isVisible()

    toggle = win._tray_manager._toggle_action
    toggle.trigger()                           # tray Disable
    assert not engine.is_enabled and not win._toggle.isChecked() and engine.active_channels == 0
    toggle.trigger()                           # tray Enable
    assert engine.is_enabled and win._toggle.isChecked()

    quit_called = []
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: quit_called.append(1)))
    next(a for a in menu.actions() if "Exit" in a.text()).trigger()
    assert quit_called and win._is_quitting
    assert not engine._is_running                   # resources released on exit


def test_close_and_minimize_go_to_tray_and_keep_working(env):
    win, engine, cfg, *_ = env
    win.close()
    assert win.isHidden() and engine._is_running and listener_active(env)
    before = win._total_meows
    engine.trigger_key(0x41)
    assert wait_for(lambda: win._total_meows == before + 1), "must keep meowing while in tray"

    win.show()
    win.showMinimized()
    assert wait_for(lambda: win.isHidden())
    before = win._total_meows
    engine.trigger_key(0x42)
    assert wait_for(lambda: win._total_meows == before + 1)
    win._tray_manager.show_window_requested.emit()
    assert win.isVisible() and not win.isMinimized()


def listener_active(env):
    return env[4].is_active


def test_close_without_a_tray_quits_instead_of_orphaning(env):
    win, engine, *_ = env
    win._tray_manager.is_available = lambda: False
    win.close()
    assert not engine._is_running


def test_settings_are_persisted_after_changes(env):
    win, engine, cfg, cfg_mgr, _ = env
    click_segment(win._personality, 3)
    click_segment(win._intensity, 2)
    win._volume_slider.setValue(33)
    win._toggle.click()
    wait(700)                                      # debounce
    saved = cfg_mgr.load()
    assert (saved.personality, saved.intensity, saved.volume, saved.enabled) == ("DEEP CAT", "CHAOS", 33, False)


def test_saved_personality_is_applied_at_startup(qapp, sound_manager, tmp_path):
    cfg = AppConfig(enabled=True, volume=50, intensity="CHILL", personality="KITTEN")
    engine = AudioEngine(sound_manager=sound_manager, intensity="NORMAL", volume=50, enabled=True)
    listener = KeyboardListener(on_key_down=engine.trigger_key)
    win = MainWindow(cfg, ConfigManager(tmp_path / "s.json"), engine, listener, ICONS)
    try:
        assert sound_manager.current_personality == "KITTEN"
        assert engine._intensity == "CHILL"
        assert win._personality.current() == "KITTEN" and win._intensity.current() == "CHILL"
    finally:
        win._is_quitting = True
        win._tick_timer.stop()
        engine.shutdown()
        win._tray_manager.hide()


def test_visualizer_colours_follow_pitch_and_personality(env):
    win, engine, *_ = env
    vis = win._keyboard_visualizer
    m = engine.pitch_mapper
    lo, hi = pitch_color(0.88), pitch_color(1.20)
    assert lo != hi
    assert m.pitch_for(0x5A) < m.pitch_for(0x70)            # Z (low row) below F1
    for key in (0x41, 0x20, 0x0D):
        vis.trigger_key_visual(m.get_key_profile(key))
        assert vis._glow[key] == 1.0
    assert wait_for(lambda: not vis._glow, 3000), "glow must fade out"
    pix = win.grab()
    assert not pix.isNull() and pix.width() >= 760
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        vis.trigger_key_visual(m.get_key_profile(0x48))
        vis.trigger_key_visual(m.get_key_profile(0x49))
        win.grab().save(str(Path(SHOTS) / "window.png"))
