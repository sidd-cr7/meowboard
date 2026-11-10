"""
Windows Autostart Registration utility.
Manages HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run entries.
"""
import sys
import os
from pathlib import Path
from typing import Optional

from .logger import logger

REG_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "MEOWBOARD"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_autostart_enabled() -> bool:
    """Checks if MEOWBOARD is registered in HKCU Run key."""
    if not is_windows():
        return False

    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_SUBKEY, 0, winreg.KEY_READ) as key:
            try:
                val, _ = winreg.QueryValueEx(key, APP_REG_NAME)
                return bool(val)
            except FileNotFoundError:
                return False
    except Exception as e:
        logger.debug("Error checking autostart registry: %s", e)
        return False


def set_autostart(enable: bool, executable_path: Optional[str] = None) -> bool:
    """Enables or disables autostart in Windows HKCU Run."""
    if not is_windows():
        return False

    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_SUBKEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                if not executable_path:
                    # If running as packaged frozen app
                    if getattr(sys, "frozen", False):
                        executable_path = sys.executable
                    else:
                        # If running from python source, point to run_meowboard.bat or pythonw
                        project_root = Path(__file__).resolve().parent.parent.parent
                        bat_path = project_root / "run_meowboard.bat"
                        if bat_path.exists():
                            executable_path = f'"{bat_path}"'
                        else:
                            executable_path = f'"{sys.executable}" "{project_root / "main.py"}"'

                winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, str(executable_path))
                logger.info("Enabled Windows autostart: %s", executable_path)
            else:
                try:
                    winreg.DeleteValue(key, APP_REG_NAME)
                    logger.info("Disabled Windows autostart")
                except FileNotFoundError:
                    pass
            return True
    except Exception as e:
        logger.error("Failed to update autostart setting: %s", e)
        return False
