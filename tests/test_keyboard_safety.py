"""
Keyboard SAFETY tests for the passive listener.

Tests inject only F24 (VK 0x87), a key no application binds, with SendInput.
(SendInput appears ONLY in these tests, never in the application.)
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

from meowboard.core import keyboard_listener as kl
from meowboard.core.audio_engine import QUEUE_MAX, AudioEngine
from meowboard.core.keyboard_listener import KeyboardListener, resolve_vk
from meowboard.core.sound_manager import SoundManager

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

VK_F24 = 0x87
ROOT = Path(__file__).resolve().parent.parent
user32 = ctypes.WinDLL("user32", use_last_error=True)


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


def f24(up: bool):
    i = INPUT(type=1)
    i.u.ki = KEYBDINPUT(wVk=VK_F24, wScan=0, dwFlags=2 if up else 0, time=0, dwExtraInfo=0)
    assert user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT)) == 1


def tap_f24(n=1):
    for _ in range(n):
        f24(False)
        f24(True)


def wait_for(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


@pytest.fixture(autouse=True)
def release_f24():
    yield
    f24(True)


def make_listener(cb, **kw):
    l = KeyboardListener(on_key_down=cb, ignore_injected=False, **kw)
    assert l.start(), "listener failed to start"
    return l


# ---------------------------------------------------------------- static guarantees

def test_source_never_hooks_suppresses_or_injects():
    src = Path(kl.__file__).read_text(encoding="utf-8")
    code = "\n".join(l.split("#")[0] for l in src.splitlines())
    # strip the module docstring (it names these APIs to say they are NOT used)
    code = code.split('"""', 2)[2]
    for banned in ("SetWindowsHookEx", "CallNextHookEx", "SendInput", "keybd_event", "BlockInput",
                   "RIDEV_NOLEGACY", "RIDEV_CAPTUREMOUSE", "RIDEV_APPKEYS", "RIDEV_NOHOTKEYS", "mouse_event"):
        assert banned not in code, f"{banned} must never be used"


def test_only_inputsink_flag_is_registered():
    assert kl.RIDEV_INPUTSINK == 0x100
    # Flags that would remove/steal keys from other apps are not even defined
    for name in ("RIDEV_NOLEGACY", "RIDEV_CAPTUREMOUSE", "RIDEV_APPKEYS", "RIDEV_NOHOTKEYS", "RIDEV_EXCLUDE"):
        assert not hasattr(kl, name)


def test_resolve_vk_left_right_modifiers():
    assert resolve_vk(0x10, 0x2A, 0) == 0xA0 and resolve_vk(0x10, 0x36, 0) == 0xA1
    assert resolve_vk(0x11, 0x1D, 0) == 0xA2 and resolve_vk(0x11, 0x1D, 2) == 0xA3
    assert resolve_vk(0x12, 0x38, 0) == 0xA4 and resolve_vk(0x12, 0x38, 2) == 0xA5
    assert resolve_vk(0xFF, 0, 0) == 0 and resolve_vk(0, 0, 0) == 0
    for vk in (0x41, 0x31, 0x70, 0x60, 0x25, 0xBA, 0x5B, 0x20, 0x0D):
        assert resolve_vk(vk, 0, 0) == vk


# ---------------------------------------------------------------- detection

def test_rawinput_backend_is_used_and_detects_keydown():
    got = []
    l = make_listener(got.append)
    try:
        assert l.backend == "rawinput"
        tap_f24()
        assert wait_for(lambda: got == [VK_F24]), got
    finally:
        l.stop()


def test_key_repeat_every_keydown_detected():
    got = []
    l = make_listener(got.append)
    try:
        for _ in range(8):      # held key => Windows sends repeated key-downs
            f24(False)
        f24(True)
        assert wait_for(lambda: len(got) == 8), len(got)
    finally:
        l.stop()


def test_keyup_does_not_trigger():
    got = []
    l = make_listener(got.append)
    try:
        f24(True)
        f24(True)
        time.sleep(0.15)
        assert got == []
    finally:
        l.stop()


def test_rapid_burst_all_delivered():
    got = []
    l = make_listener(got.append)
    try:
        tap_f24(500)
        assert wait_for(lambda: len(got) == 500, 5), len(got)
    finally:
        l.stop()


def test_injected_input_ignored_by_default():
    got = []
    l = KeyboardListener(on_key_down=got.append)  # ignore_injected=True default
    assert l.start()
    try:
        tap_f24(3)
        assert wait_for(lambda: l.events_ignored == 3)
        assert got == []
    finally:
        l.stop()


# ---------------------------------------------------------------- the keyboard must never be affected

def wait_ready(p):
    for line in p.stdout:          # child also prints pygame banner / log lines
        if line.strip() == "READY":
            return
    raise AssertionError("child exited before READY")


def spawn_observer(wedge: bool):
    """Independent consumer of the keyboard in ANOTHER process (Raw Input is one registration per process)."""
    body = "time.sleep(60)" if wedge else "print('E',flush=True)"
    code = (
        "import sys,time;sys.path.insert(0,r'%s');"
        "from meowboard.core.keyboard_listener import KeyboardListener;"
        "l=KeyboardListener(on_key_down=lambda v:%s,ignore_injected=False);"
        "assert l.start();print('READY',flush=True);time.sleep(60)" % (ROOT, body)
    )
    p = subprocess.Popen([sys.executable, "-I", "-c", code], stdout=subprocess.PIPE, text=True)
    wait_ready(p)
    return p


def test_wedged_listener_cannot_slow_or_block_system_keyboard():
    """A callback stuck for seconds (worst case: frozen audio) must not delay anything else."""
    release = threading.Event()
    blocked = []

    def stuck(vk):
        blocked.append(vk)
        release.wait(5)

    watcher = spawn_observer(wedge=False)       # separate process, healthy consumer
    count = []
    threading.Thread(target=lambda: [count.append(1) for ln in watcher.stdout if ln.strip() == 'E'], daemon=True).start()
    victim = make_listener(stuck)
    try:
        tap_f24()                              # wedges `victim`
        assert wait_for(lambda: blocked)
        t0 = time.perf_counter()
        tap_f24(30)                            # system input while victim is wedged
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"60 SendInput events with wedged listener: {elapsed_ms:.1f} ms")
        assert elapsed_ms < 250
        f24(False)
        assert user32.GetAsyncKeyState(VK_F24) & 0x8000, "system key state must update immediately"
        f24(True)
        assert wait_for(lambda: len(count) == 32, 3), len(count)  # other apps still get every key
    finally:
        release.set()
        victim.stop()
        watcher.kill()
        watcher.wait(5)


def test_wedged_audio_engine_handoff_is_bounded_and_nonblocking():
    mgr = SoundManager(assets_dir=ROOT / "meowboard" / "assets" / "sounds")
    engine = AudioEngine(sound_manager=mgr, intensity="CHAOS", volume=50, enabled=True)
    l = make_listener(engine.trigger_key)
    try:
        max_pending = 0
        with engine._lock:                      # audio thread wedged
            t0 = time.perf_counter()
            tap_f24(300)
            ms = (time.perf_counter() - t0) * 1000
            wait_for(lambda: l.events_seen >= 300, 3)
            max_pending = engine.pending_events
        print(f"300 taps with wedged audio: {ms:.1f} ms, pending={max_pending}, seen={l.events_seen}")
        assert ms < 1500
        assert max_pending <= QUEUE_MAX
        assert l.events_seen == 300
    finally:
        l.stop()
        engine.shutdown()


# ---------------------------------------------------------------- lifecycle / cleanup / crash

def test_stop_releases_everything_and_stops_events():
    got = []
    l = make_listener(got.append)
    th = l._thread
    l.stop()
    assert not l.is_active and l._hwnd is None
    assert not th.is_alive()
    tap_f24(3)
    time.sleep(0.2)
    assert got == []
    l.stop()  # idempotent


def test_restart_and_many_cycles_do_not_leak_threads():
    before = threading.active_count()
    for _ in range(25):
        l = KeyboardListener(on_key_down=lambda vk: None, ignore_injected=False)
        assert l.start()
        l.stop()
    assert threading.active_count() <= before
    got = []
    l = make_listener(got.append)
    try:
        tap_f24()
        assert wait_for(lambda: got == [VK_F24])
    finally:
        l.stop()


def test_hard_kill_of_listening_process_leaves_keyboard_working():
    """Simulates a crash: kill -9 a process while it is listening, then verify input still flows."""
    code = (
        "import sys,time;sys.path.insert(0,r'%s');"
        "from meowboard.core.keyboard_listener import KeyboardListener;"
        "l=KeyboardListener(on_key_down=lambda v:time.sleep(60),ignore_injected=False);"
        "assert l.start();print('READY',flush=True);time.sleep(60)" % ROOT
    )
    p = subprocess.Popen([sys.executable, "-I", "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        wait_ready(p)
        tap_f24()                    # wedge the child's callback, then crash it
        time.sleep(0.2)
    finally:
        p.kill()
        p.wait(5)
    got = []
    l = make_listener(got.append)
    try:
        t0 = time.perf_counter()
        tap_f24(5)
        assert (time.perf_counter() - t0) < 0.25
        assert wait_for(lambda: len(got) == 5)
        f24(False)
        assert user32.GetAsyncKeyState(VK_F24) & 0x8000
        f24(True)
    finally:
        l.stop()


def test_polling_fallback_still_works():
    got = []
    l = KeyboardListener(on_key_down=got.append, backend="poll")
    assert l.start() and l.backend == "poll"
    try:
        f24(False)
        assert wait_for(lambda: got == [VK_F24])
        f24(True)
    finally:
        l.stop()
