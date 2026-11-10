"""
Configuration manager for MEOWBOARD.
Saves and loads user preferences locally without any cloud services or external telemetry.
"""
import json
import os
from pathlib import Path
from typing import Optional

from ..config.settings import AppConfig
from .logger import logger


class ConfigManager:
    """Handles persistence of AppConfig to local disk."""

    def __init__(self, config_path: Optional[Path] = None):
        if config_path:
            self._path = Path(config_path)
        else:
            # Prefer ~/.meowboard/settings.json
            self._path = Path.home() / ".meowboard" / "settings.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppConfig:
        """Loads configuration from disk, returning defaults if not found or corrupted."""
        if not self._path.exists():
            logger.info("Configuration file not found. Creating default configuration.")
            config = AppConfig()
            self.save(config)
            return config

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = AppConfig.from_dict(data)
            logger.info("Configuration successfully loaded from %s", self._path)
            return config
        except Exception as e:
            logger.warning("Failed to parse config file (%s), resetting to defaults. Error: %s", self._path, e)
            default_config = AppConfig()
            self.save(default_config)
            return default_config

    def save(self, config: AppConfig) -> bool:
        """Saves current configuration to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temporary file first then atomic replace to prevent corrupt files
            temp_path = self._path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, indent=4)
            temp_path.replace(self._path)
            logger.debug("Configuration saved to %s", self._path)
            return True
        except Exception as e:
            logger.error("Failed to save configuration to %s: %s", self._path, e)
            return False
