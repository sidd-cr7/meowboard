"""Tests for AudioEngine channel management and stealing."""
import time
import tempfile
from pathlib import Path
import pytest

from meowboard.core.sound_manager import SoundManager
from meowboard.core.audio_engine import AudioEngine
from meowboard.config.settings import INTENSITY_CHANNELS


@pytest.fixture(scope="module")
def shared_sound_manager():
    # Use temporary directory for assets
    with tempfile.TemporaryDirectory() as tmpdir:
        assets_dir = Path(tmpdir) / "sounds"
        mgr = SoundManager(assets_dir=assets_dir)
        yield mgr


def test_audio_engine_channel_modes(shared_sound_manager):
    played_keys = []

    engine = AudioEngine(
        sound_manager=shared_sound_manager,
        intensity="CHILL",
        volume=80,
        enabled=True,
        on_key_played=lambda prof: played_keys.append(prof.name),
    )

    try:
        # Check intensity channels
        assert engine._intensity == "CHILL"
        assert INTENSITY_CHANNELS["CHILL"] == 4

        # Switch to NORMAL
        engine.set_intensity("NORMAL")
        assert engine._intensity == "NORMAL"
        assert INTENSITY_CHANNELS["NORMAL"] == 12

        # Switch to CHAOS
        engine.set_intensity("CHAOS")
        assert engine._intensity == "CHAOS"
        assert INTENSITY_CHANNELS["CHAOS"] == 24

    finally:
        engine.shutdown()


def test_rapid_burst_and_channel_stealing(shared_sound_manager):
    played_keys = []
    engine = AudioEngine(
        sound_manager=shared_sound_manager,
        intensity="CHILL",  # 4 channels
        volume=80,
        enabled=True,
        on_key_played=lambda prof: played_keys.append(prof.name),
    )

    try:
        # Rapid burst of 20 keystrokes within 20 milliseconds
        # The channel limit is 4 channels.
        # Older sounds MUST be stolen without backlog accumulating.
        for vk in range(0x41, 0x55):  # 'A' through 'T' (20 keys)
            engine.trigger_key(vk)

        # Allow worker thread to drain
        time.sleep(0.15)

        # Ensure all 20 keys were processed promptly
        assert len(played_keys) == 20
        # Ensure active channels never exceed 4 (the CHILL limit)
        busy_channels = sum(1 for ch in engine._channels if ch.get_busy())
        assert busy_channels <= 4

    finally:
        engine.shutdown()


def test_mute_behavior(shared_sound_manager):
    played_keys = []
    engine = AudioEngine(
        sound_manager=shared_sound_manager,
        intensity="NORMAL",
        volume=80,
        enabled=False,  # MUTED
        on_key_played=lambda prof: played_keys.append(prof.name),
    )

    try:
        engine.trigger_key(0x41)
        time.sleep(0.05)
        # Should not play sounds when muted
        assert len(played_keys) == 0
    finally:
        engine.shutdown()
