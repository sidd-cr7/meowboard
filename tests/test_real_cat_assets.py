"""
Tests for Real Cat Audio Recordings and Asset Manifest.
"""
import json
from pathlib import Path
import wave
import pytest
import numpy as np

from meowboard.core.sound_manager import SoundManager
from meowboard.config.settings import PERSONALITIES

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "meowboard" / "assets"
SOUNDS_DIR = ASSETS_DIR / "sounds"
SOURCE_DIR = ASSETS_DIR / "source_recordings"
MANIFEST_JSON = ASSETS_DIR / "ASSET_MANIFEST.json"
MANIFEST_MD = ASSETS_DIR / "ASSET_MANIFEST.md"


def test_asset_manifest_exists():
    assert MANIFEST_JSON.exists(), "ASSET_MANIFEST.json must exist"
    assert MANIFEST_MD.exists(), "ASSET_MANIFEST.md must exist"

    with open(MANIFEST_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "recordings" in data
    assert len(data["recordings"]) >= 15


def test_source_recordings_preserved():
    """Requirement: Maintain original recordings as source assets."""
    assert SOURCE_DIR.exists()
    sources = list(SOURCE_DIR.glob("*.wav"))
    assert len(sources) >= 15, "Must retain at least 15 original source recordings"


def test_processed_sounds_exist_and_are_valid():
    """Verifies that all 20 real cat recordings exist, are trimmed and normalized."""
    categories = ["standard", "space", "enter", "backspace", "escape"]
    personalities = ["normal_cat", "kitten", "angry_cat", "deep_cat"]

    for p in personalities:
        p_dir = SOUNDS_DIR / p
        assert p_dir.exists(), f"Personality directory {p} missing"
        for cat in categories:
            wav_path = p_dir / f"{cat}.wav"
            assert wav_path.exists(), f"Missing audio asset: {wav_path}"

            # Check WAV properties
            with wave.open(str(wav_path), "rb") as wf:
                assert wf.getframerate() == 44100, f"{wav_path} must be 44.1 kHz"
                assert wf.getsampwidth() == 2, f"{wav_path} must be 16-bit PCM"
                assert wf.getnchannels() in (1, 2), f"{wav_path} channel count invalid"
                dur = wf.getnframes() / wf.getframerate()
                # Must be trimmed silence (shorter than 1.6s, original was 5.0s)
                assert 0.15 <= dur <= 1.6, f"{wav_path} duration {dur:.2f}s outside expected trimmed range"

                frames = wf.readframes(wf.getnframes())
                audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                peak = np.max(np.abs(audio))
                rms = np.sqrt(np.mean(audio ** 2))

                # Loudness normalization: peak should be near -1.5 dBFS (~0.84 +/- 0.05)
                assert 0.70 <= peak <= 0.90, f"{wav_path} peak {peak:.2f} not normalized"
                # Non-empty signal
                assert rms > 0.01, f"{wav_path} rms {rms:.4f} too quiet"


def test_sound_manager_preloads_real_recordings():
    """Requirement: Preload real samples into memory and generate pitch variations."""
    mgr = SoundManager(assets_dir=SOUNDS_DIR)

    # Check that SoundManager loaded the real assets
    for p in PERSONALITIES:
        mgr.set_personality(p)
        # Test standard, space, enter, backspace, escape
        for vk in [0x41, 0x20, 0x0D, 0x08, 0x1B]:
            sound, prof = mgr.get_sound_for_key(vk)
            assert sound is not None
            assert prof is not None
