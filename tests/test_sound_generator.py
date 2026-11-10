"""Tests for Procedural Cat Sound Generator and SoundManager."""
import tempfile
from pathlib import Path
import numpy as np

from meowboard.core.sound_generator import generate_meow_pcm, save_pcm_to_wav, ensure_sound_assets
from meowboard.core.sound_manager import SoundManager
from meowboard.config.settings import PERSONALITIES, PERSONALITY_NORMAL, PERSONALITY_KITTEN


def test_generate_meow_pcm_all_personalities():
    for p in PERSONALITIES:
        pcm, sr = generate_meow_pcm(personality=p, category="standard")
        assert len(pcm) > 0
        assert sr == 44100
        # Peak should be normalized under 1.0 (headroom)
        assert np.max(np.abs(pcm)) <= 0.85
        # Energy should be non-zero
        assert np.mean(pcm ** 2) > 0.001


def test_generate_categories():
    categories = ["standard", "space", "enter", "backspace", "escape"]
    for cat in categories:
        pcm, sr = generate_meow_pcm(personality=PERSONALITY_NORMAL, category=cat)
        assert len(pcm) > 0


def test_sound_manager_preloading():
    with tempfile.TemporaryDirectory() as tmpdir:
        assets_dir = Path(tmpdir) / "sounds"
        mgr = SoundManager(assets_dir=assets_dir)

        # Assets should be generated and preloaded
        assert mgr is not None

        # Space key
        sound, profile = mgr.get_sound_for_key(0x20)
        assert profile.name == "SPACE"
        assert sound is not None

        # Standard key A
        sound_a, prof_a = mgr.get_sound_for_key(0x41)
        assert prof_a.name == "A"
        assert sound_a is not None

        # Switch personality
        mgr.set_personality(PERSONALITY_KITTEN)
        sound_k, _ = mgr.get_sound_for_key(0x41)
        assert sound_k is not None
