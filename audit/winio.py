"""Win32 helpers for the audit: SendInput, focus control, process metrics. Audit-only code."""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

ROOT = Path(__file__).resolve().parent.parent

KEYEVENTF_EXTENDEDKEY = 0x1
KEYEVENTF_KEYUP = 0x2
KEYEVENTF_SCANCODE = 0x8

# VKs whose scancode needs the extended flag
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x6F, 0xA3, 0xA5, 0x5B, 0x5C, 0x5D, 0x2C, 0x90}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetKeyState.argtypes = [ctypes.c_int]
user32.GetKeyState.restype = ctypes.c_short
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def _ki(vk, up=False):
    i = INPUT(type=1)
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
    i.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return i


def send(events):
    """events: list of (vk, up). One atomic SendInput call."""
    arr = (INPUT * len(events))(*[_ki(vk, up) for vk, up in events])
    n = user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))
    if n != len(arr):
        raise OSError(f"SendInput delivered {n}/{len(arr)} (UIPI/desktop locked?)")


def tap(vk, delay=0.0):
    send([(vk, False)])
    if delay:
        time.sleep(delay)
    send([(vk, True)])


def chord(*vks, hold=0.03):
    """Press vks in order, then release in reverse (e.g. Ctrl, C)."""
    for vk in vks:
        send([(vk, False)])
        time.sleep(hold)
    for vk in reversed(vks):
        send([(vk, True)])
        time.sleep(hold)


def key_is_down(vk) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def toggled(vk) -> bool:
    return bool(user32.GetKeyState(vk) & 1)


def fg():
    return user32.GetForegroundWindow()


def window_class(hwnd) -> str:
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, b, 256)
    return b.value


def window_title(hwnd) -> str:
    b = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, b, 256)
    return b.value


def force_foreground(hwnd, tries=8) -> bool:
    """Bring our own window to the front (Alt-tap unlocks SetForegroundWindow)."""
    for _ in range(tries):
        if fg() == hwnd:
            return True
        send([(0xA4, False)])
        send([(0xA4, True)])
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.15)
    return fg() == hwnd


# ---- process metrics (no psutil)
class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]


def rss_mb(handle=None) -> float:
    c = PROCESS_MEMORY_COUNTERS()
    c.cb = ctypes.sizeof(c)
    psapi.GetProcessMemoryInfo(handle or kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.WorkingSetSize / 1e6


def handle_count() -> int:
    n = wintypes.DWORD()
    kernel32.GetProcessHandleCount(kernel32.GetCurrentProcess(), ctypes.byref(n))
    return n.value


# ---- launching the real application
def launch_app(kind="source", enabled=True, home=None):
    """Starts the real MEOWBOARD (source main.py or dist exe) with an isolated settings dir.
    Returns (Popen, home_dir)."""
    import json, tempfile
    home = Path(home or tempfile.mkdtemp(prefix="meow_audit_"))
    cfg_dir = home / ".meowboard"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "settings.json").write_text(json.dumps({
        "enabled": enabled, "volume": 40, "intensity": "NORMAL", "personality": "NORMAL CAT",
        "start_with_windows": False, "minimize_to_tray_on_close": True}), encoding="utf-8")
    env = dict(os.environ, USERPROFILE=str(home), HOME=str(home))
    if kind == "exe":
        cmd = [str(ROOT / "dist" / "MEOWBOARD" / "MEOWBOARD.exe")]
        cwd = str(ROOT / "dist" / "MEOWBOARD")
    else:
        cmd = [str(ROOT / ".venv" / "Scripts" / "pythonw.exe"), "main.py"]
        cwd = str(ROOT)
    p = subprocess.Popen(cmd, cwd=cwd, env=env, creationflags=0x08000000)  # CREATE_NO_WINDOW
    return p, home


def kill_tree(p):
    if p and p.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
