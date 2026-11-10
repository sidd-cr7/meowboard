"""
End-to-End Integration Tests for MEOWBOARD (Tests 1-12 from Specifications).
"""
import time
import pytest
from pathlib import Path

from meowboard.config.settings import (
    AppConfig,
    INTENSITY_CHANNELS,
    PERSONALITIES,
    PERSONALITY_NORMAL,
    PERSONALITY_KITTEN,
    PERSONALITY_ANGRY,
    PERSONALITY_DEEP,
)
from meowboard.core.pitch_mapper import PitchMapper
from meowboard.core.sound_manager import SoundManager
from meowboard.core.audio_engine import AudioEngine
from meowboard.core.keyboard_listener import KeyboardListener
from meowboard.utils.config_manager import ConfigManager


@pytest.fixture(scope="module")
def project_sound_manager():
    assets_dir = Path(__file__).resolve().parent.parent / "meowboard" / "assets" / "sounds"
    mgr = SoundManager(assets_dir=assets_dir)
    return mgr


def test_e2e_stack_initialization_and_key_triggers(project_sound_manager):
    """TEST 1 & 2: Launch stack and simulate typing rapid key sequences."""
    events_triggered = []

    engine = AudioEngine(
        sound_manager=project_sound_manager,
        intensity="NORMAL",
        volume=80,
        enabled=True,
        on_key_played=lambda prof: events_triggered.append(prof),
    )

    try:
        # Simulate typing sentence "THE QUICK BROWN CAT JUMPED OVER THE LAZY DOG"
        test_keys = [
            0x54, 0x48, 0x45, 0x20,  # "THE "
            0x51, 0x55, 0x49, 0x43, 0x4B, 0x20,  # "QUICK "
            0x42, 0x52, 0x4F, 0x57, 0x4E, 0x20,  # "BROWN "
            0x43, 0x41, 0x54, 0x0D,  # "CAT\n"
        ]

        for vk in test_keys:
            engine.trigger_key(vk)

        time.sleep(0.2)
        assert len(events_triggered) == len(test_keys)

        # Verify key names and pitch categories
        names = [p.name for p in events_triggered]
        assert "SPACE" in names
        assert "ENTER" in names
        assert "T" in names
        assert "C" in names

    finally:
        engine.shutdown()


def test_e2e_key_repeat_hold(project_sound_manager):
    """TEST 3: Hold down a key (generates repeated WM_KEYDOWN events)."""
    events = []
    engine = AudioEngine(
        sound_manager=project_sound_manager,
        intensity="NORMAL",
        volume=80,
        enabled=True,
        on_key_played=lambda prof: events.append(prof),
    )

    try:
        # Simulate 15 repeated key-down events for held key 'A' (VK 0x41)
        for _ in range(15):
            engine.trigger_key(0x41)
            time.sleep(0.01)

        time.sleep(0.1)
        assert len(events) == 15
        assert all(p.name == "A" for p in events)
    finally:
        engine.shutdown()


def test_e2e_bounded_channels_under_continuous_load(project_sound_manager):
    """TEST 4: Continuous typing burst. Channels remain strictly bounded."""
    engine = AudioEngine(
        sound_manager=project_sound_manager,
        intensity="CHILL",  # 4 channels
        volume=80,
        enabled=True,
    )

    try:
        # Trigger 50 rapid key events
        for i in range(50):
            engine.trigger_key(0x41 + (i % 26))

        time.sleep(0.1)
        busy_channels = sum(1 for ch in engine._channels if ch.get_busy())
        # Channel count must never exceed CHILL limit (4)
        assert busy_channels <= 4

    finally:
        engine.shutdown()


def test_e2e_switch_intensity_modes(project_sound_manager):
    """TEST 5: Switch between all three intensity modes while typing."""
    engine = AudioEngine(
        sound_manager=project_sound_manager,
        intensity="CHILL",
        volume=70,
        enabled=True,
    )

    try:
        # Chill
        assert engine._intensity == "CHILL"
        engine.trigger_key(0x41)

        # Switch to Normal
        engine.set_intensity("NORMAL")
        assert engine._intensity == "NORMAL"
        engine.trigger_key(0x42)

        # Switch to Chaos
        engine.set_intensity("CHAOS")
        assert engine._intensity == "CHAOS"
        engine.trigger_key(0x43)

        time.sleep(0.1)
    finally:
        engine.shutdown()


def test_e2e_switch_cat_personalities(project_sound_manager):
    """TEST 6: Switch between all 4 cat personalities."""
    engine = AudioEngine(
        sound_manager=project_sound_manager,
        intensity="NORMAL",
        volume=75,
        enabled=True,
    )

    try:
        for p in PERSONALITIES:
            engine.set_personality(p)
            assert project_sound_manager._current_personality == p
            # Trigger sounds for that personality
            engine.trigger_key(0x41)  # A
            engine.trigger_key(0x20)  # Space
            engine.trigger_key(0x0D)  # Enter
            engine.trigger_key(0x1B)  # Esc
            time.sleep(0.05)

    finally:
        engine.shutdown()


def test_e2e_special_key_combinations(project_sound_manager):
    """TEST 7: Combinations involving Shift, Ctrl, Alt, Backspace, Enter, Esc, Function."""
    combos = [
        0x10,  # SHIFT
        0x11,  # CTRL
        0x12,  # ALT
        0x08,  # BACKSPACE
        0x0D,  # ENTER
        0x1B,  # ESC
        0x70,  # F1
        0x74,  # F5
        0x7B,  # F12
    ]
    played = []
    engine = AudioEngine(
        sound_manager=project_sound_manager,
        intensity="NORMAL",
        volume=80,
        enabled=True,
        on_key_played=lambda prof: played.append(prof),
    )

    try:
        for vk in combos:
            engine.trigger_key(vk)

        time.sleep(0.1)
        assert len(played) == len(combos)
        played_names = [p.name for p in played]
        assert "SHIFT" in played_names
        assert "CTRL" in played_names
        assert "ALT" in played_names
        assert "BACKSPACE" in played_names
        assert "ENTER" in played_names
        assert "ESC" in played_names
        assert "F1" in played_names

    finally:
        engine.shutdown()


def test_e2e_mute_and_resume(project_sound_manager):
    """TEST 9 & 10: Instant mute and re-enable."""
    played = []
    engine = AudioEngine(
        sound_manager=project_sound_manager,
        intensity="NORMAL",
        volume=80,
        enabled=True,
        on_key_played=lambda prof: played.append(prof),
    )

    try:
        # Active
        engine.trigger_key(0x41)
        time.sleep(0.05)
        assert len(played) == 1

        # Mute
        engine.set_enabled(False)
        assert not engine.is_enabled
        engine.trigger_key(0x42)
        engine.trigger_key(0x43)
        time.sleep(0.05)
        # Should not have played new keys while muted
        assert len(played) == 1

        # Re-enable
        engine.set_enabled(True)
        assert engine.is_enabled
        engine.trigger_key(0x44)
        time.sleep(0.05)
        assert len(played) == 2

    finally:
        engine.shutdown()


def test_e2e_resource_release_on_shutdown(project_sound_manager):
    """TEST 12: Verify all hooks and audio channels are released cleanly."""
    listener = KeyboardListener(on_key_down=lambda vk: None)
    engine = AudioEngine(
        sound_manager=project_sound_manager,
        intensity="NORMAL",
        volume=80,
        enabled=True,
    )

    listener.start()
    time.sleep(0.05)

    # Shutdown
    listener.stop()
    engine.shutdown()

    assert not listener.is_active
    assert not engine._is_running
    # Verify mixer is closed and released
    import pygame
    assert pygame.mixer.get_init() is None
