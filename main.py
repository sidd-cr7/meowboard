"""
MEOWBOARD - System-Wide Windows Keyboard Meow Sound Engine.
Entry Point.
"""
import argparse
import atexit
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from meowboard.config.settings import (
    AppConfig,
    DEFAULT_SAMPLE_RATE,
)
from meowboard.core.audio_engine import AudioEngine
from meowboard.core.keyboard_listener import KeyboardListener
from meowboard.core.pitch_mapper import PitchMapper
from meowboard.core.sound_manager import SoundManager
from meowboard.gui.main_window import MainWindow
from meowboard.utils.config_manager import ConfigManager
from meowboard.utils.logger import logger


def parse_args():
    parser = argparse.ArgumentParser(description="MEOWBOARD - System-Wide Keyboard Meow Sound Engine")
    parser.add_argument("--minimized", action="store_true", help="Start minimized directly to the system tray")
    parser.add_argument("--test-only", action="store_true", help="Run self-tests and exit")
    return parser.parse_args()


def main():
    args = parse_args()

    # Single instance only: stacked copies were the source of runaway behaviour.
    _mutex = None
    if sys.platform == "win32":
        try:
            import ctypes
            _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\MEOWBOARD_SingleInstance")
            if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                logger.warning("MEOWBOARD is already running; exiting.")
                sys.exit(0)
        except SystemExit:
            raise
        except Exception:
            pass

    # Enable High-DPI Scaling for Windows
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("MEOWBOARD")
    app.setOrganizationName("Meowboard")
    app.setQuitOnLastWindowClosed(False)  # Keep alive in system tray

    # Base paths (supports both source script and PyInstaller frozen executable)
    if getattr(sys, "frozen", False):
        base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base_dir = Path(__file__).resolve().parent

    assets_dir = base_dir / "meowboard" / "assets"
    if not assets_dir.exists():
        assets_dir = Path(sys.executable).parent / "_internal" / "meowboard" / "assets"
    if not assets_dir.exists():
        assets_dir = Path(sys.executable).parent / "meowboard" / "assets"

    sounds_dir = assets_dir / "sounds"
    icons_dir = assets_dir / "icons"

    logger.info("Initializing MEOWBOARD...")

    # 1. Load Local Configuration
    config_mgr = ConfigManager()
    config = config_mgr.load()

    # 2. Initialize Core Subsystems
    pitch_mapper = PitchMapper()
    sound_manager = SoundManager(assets_dir=sounds_dir, pitch_mapper=pitch_mapper, background_preload=True)

    audio_engine = AudioEngine(
        sound_manager=sound_manager,
        intensity=config.intensity,
        volume=config.volume,
        enabled=config.enabled,
    )

    # 3. Initialize Global Windows Keyboard Listener
    keyboard_listener = KeyboardListener(
        on_key_down=audio_engine.trigger_key,
        ignore_injected=False,  # never miss a key (RDP/virtual keyboards report no device)
    )

    hook_success = keyboard_listener.start()
    if not hook_success:
        logger.warning("Global keyboard hook could not be established immediately.")

    # 4. Initialize Desktop GUI
    main_window = MainWindow(
        config=config,
        config_manager=config_mgr,
        audio_engine=audio_engine,
        keyboard_listener=keyboard_listener,
        icons_dir=icons_dir,
    )

    if not args.minimized:
        main_window.show()
    else:
        logger.info("Starting minimized to system tray")

    logger.info("MEOWBOARD is ready! Press any key anywhere in Windows to meow 🐈")

    # Guarantee cleanup on any exit path (the observer is hook-free, so the
    # keyboard is unaffected even if this process dies abruptly).
    def _cleanup():
        try:
            keyboard_listener.stop()
        except Exception:
            pass
        try:
            audio_engine.shutdown()
        except Exception:
            pass

    atexit.register(_cleanup)

    exit_code = 1
    try:
        exit_code = app.exec()
    finally:
        _cleanup()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
