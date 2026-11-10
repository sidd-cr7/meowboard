"""Tests for Configuration and persistence."""
import tempfile
from pathlib import Path
from meowboard.config.settings import AppConfig, INTENSITY_CHANNELS, PERSONALITIES
from meowboard.utils.config_manager import ConfigManager


def test_default_config():
    config = AppConfig()
    assert config.enabled is True
    assert config.volume == 75
    assert config.intensity == "NORMAL"
    assert config.personality == "NORMAL CAT"
    assert config.start_with_windows is False


def test_config_save_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "test_settings.json"
        mgr = ConfigManager(config_path)

        # Initially creates defaults
        cfg = mgr.load()
        assert cfg.volume == 75

        # Modify and save
        cfg.volume = 90
        cfg.intensity = "CHAOS"
        cfg.personality = "KITTEN"
        assert mgr.save(cfg) is True

        # Reload
        reloaded = mgr.load()
        assert reloaded.volume == 90
        assert reloaded.intensity == "CHAOS"
        assert reloaded.personality == "KITTEN"


def test_invalid_config_fallback():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "corrupt.json"
        # Write corrupted JSON
        with open(config_path, "w") as f:
            f.write("INVALID JSON CONTENT {{{")

        mgr = ConfigManager(config_path)
        cfg = mgr.load()
        # Should gracefully fall back to defaults
        assert cfg.volume == 75
        assert cfg.intensity == "NORMAL"
