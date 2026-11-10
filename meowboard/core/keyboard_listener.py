"""
Passive global keyboard listener for MEOWBOARD.

SAFETY ARCHITECTURE
-------------------
MEOWBOARD never sits in the Windows keyboard input chain.

Primary backend: Windows *Raw Input* (WM_INPUT, RIDEV_INPUTSINK) on a private
message-only window. Raw Input delivers a *copy* of each physical keyboard event
to our own message queue AFTER/independent of normal delivery:
  * there is no hook procedure and therefore no CallNextHookEx to forget or return
    a wrong value from - the keyboard cannot be suppressed, delayed or modified;
  * if our thread stalls, the only effect is that our own queue grows; every other
    application keeps receiving keys normally;
  * if the process hangs or crashes, Windows discards the registration - nothing
    persists, nothing needs unregistering for the keyboard to keep working;
  * RIDEV_NOLEGACY / RIDEV_CAPTUREMOUSE / RIDEV_APPKEYS (flags that would take
    keys away from other apps) are never used.

Fallback backend: read-only GetAsyncKeyState polling (edge detection, no key-repeat).

This module never calls SetWindowsHookEx, SendInput, keybd_event or BlockInput.
Windows key-repeat is honoured: each repeated key-down Windows generates arrives as
another event. The callback must be a cheap, non-blocking hand-off (the audio engine's
bounded drop-oldest queue).
"""
import ctypes
import itertools
import sys
import threading
from ctypes import wintypes
from typing import Callable, Optional

from ..utils.logger import logger

POLL_INTERVAL_S = 0.004

# ---- Raw Input constants
WM_INPUT = 0x00FF
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
RID_INPUT = 0x10000003
RIM_TYPEKEYBOARD = 1
RIDEV_REMOVE = 0x00000001
RIDEV_INPUTSINK = 0x00000100  # receive input even when not foreground (system-wide)
RI_KEY_BREAK = 0x01
RI_KEY_E0 = 0x02
HWND_MESSAGE = -3

VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12

LRESULT = ctypes.c_ssize_t
HANDLE = ctypes.c_void_p


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", ctypes.c_ushort), ("usUsage", ctypes.c_ushort),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", HANDLE)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", HANDLE), ("wParam", ctypes.c_size_t)]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [("MakeCode", ctypes.c_ushort), ("Flags", ctypes.c_ushort),
                ("Reserved", ctypes.c_ushort), ("VKey", ctypes.c_ushort),
                ("Message", wintypes.UINT), ("ExtraInformation", wintypes.ULONG)]


class WNDCLASSW(ctypes.Structure):
    pass


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HANDLE, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t)
WNDCLASSW._fields_ = [
    ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
    ("cbWndExtra", ctypes.c_int), ("hInstance", HANDLE), ("hIcon", HANDLE),
    ("hCursor", HANDLE), ("hbrBackground", HANDLE), ("lpszMenuName", wintypes.LPCWSTR),
    ("lpszClassName", wintypes.LPCWSTR),
]

_class_counter = itertools.count()

# Polling-fallback key set (excludes mouse buttons and generic modifier codes)
_WATCHED = tuple(vk for vk in range(0x08, 0xFF) if vk not in (0x10, 0x11, 0x12))


def resolve_vk(vkey: int, make_code: int, flags: int) -> int:
    """Raw Input reports generic Shift/Ctrl/Alt; map to left/right variants. 0 = ignore."""
    if vkey == 0 or vkey == 0xFF:  # fake/escape keys (e.g. NumLock sequences)
        return 0
    e0 = bool(flags & RI_KEY_E0)
    if vkey == VK_SHIFT:
        return 0xA1 if make_code == 0x36 else 0xA0
    if vkey == VK_CONTROL:
        return 0xA3 if e0 else 0xA2
    if vkey == VK_MENU:
        return 0xA5 if e0 else 0xA4
    return vkey


class KeyboardListener:
    """Read-only keyboard observer. API: start() / stop() / is_active, on_key_down(vk)."""

    def __init__(self, on_key_down: Optional[Callable[[int], None]] = None, ignore_injected: bool = True,
                 backend: str = "auto"):
        self._on_key_down = on_key_down
        self._ignore_injected = ignore_injected
        self._requested_backend = backend  # "auto" | "rawinput" | "poll"
        self.backend: Optional[str] = None

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._start_ok = False
        self._is_running = False

        # raw input state
        self._hwnd = None
        self._wndproc = None  # keep ctypes callback alive
        self._class_name = None
        self._u32 = None
        self.events_seen = 0
        self.events_ignored = 0

        # polling state
        self._get_async_key_state = None

    # ------------------------------------------------------------------ raw input backend

    def _bind_win32(self):
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        u32.RegisterClassW.restype = wintypes.ATOM
        u32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, HANDLE]
        u32.UnregisterClassW.restype = wintypes.BOOL
        u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        HANDLE, HANDLE, HANDLE, ctypes.c_void_p]
        u32.CreateWindowExW.restype = HANDLE
        u32.DefWindowProcW.argtypes = [HANDLE, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        u32.DefWindowProcW.restype = LRESULT
        u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), HANDLE, wintypes.UINT, wintypes.UINT]
        u32.GetMessageW.restype = ctypes.c_int
        u32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u32.DispatchMessageW.restype = LRESULT
        u32.PostMessageW.argtypes = [HANDLE, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        u32.PostMessageW.restype = wintypes.BOOL
        u32.PostQuitMessage.argtypes = [ctypes.c_int]
        u32.DestroyWindow.argtypes = [HANDLE]
        u32.DestroyWindow.restype = wintypes.BOOL
        u32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
        u32.RegisterRawInputDevices.restype = wintypes.BOOL
        u32.GetRawInputData.argtypes = [HANDLE, wintypes.UINT, ctypes.c_void_p,
                                        ctypes.POINTER(wintypes.UINT), wintypes.UINT]
        u32.GetRawInputData.restype = wintypes.UINT
        k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k32.GetModuleHandleW.restype = HANDLE
        return u32, k32

    def _handle_wm_input(self, lparam: int):
        u32 = self._u32
        buf = self._buf
        size = wintypes.UINT(ctypes.sizeof(buf))
        n = u32.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))
        if n == 0 or n == 0xFFFFFFFF:
            return
        header = RAWINPUTHEADER.from_buffer(buf)
        if header.dwType != RIM_TYPEKEYBOARD:
            return
        kb = RAWKEYBOARD.from_buffer(buf, ctypes.sizeof(RAWINPUTHEADER))
        if kb.Flags & RI_KEY_BREAK:  # key-up
            return
        vk = resolve_vk(kb.VKey, kb.MakeCode, kb.Flags)
        if vk == 0:
            return
        self.events_seen += 1
        if self._ignore_injected and not header.hDevice:  # hDevice NULL => synthesized input
            self.events_ignored += 1
            return
        cb = self._on_key_down
        if cb is not None:
            try:
                cb(vk)
            except Exception as e:  # never let a callback kill the pump
                logger.debug("on_key_down error: %s", e)

    def _rawinput_thread(self):
        try:
            u32, k32 = self._bind_win32()
            self._u32 = u32
            self._buf = ctypes.create_string_buffer(256)
            hinst = k32.GetModuleHandleW(None)
            self._class_name = f"MeowboardRawInput{next(_class_counter)}_{id(self)}"

            def wndproc(hwnd, msg, wparam, lparam):
                try:
                    if msg == WM_INPUT:
                        self._handle_wm_input(lparam)
                    elif msg == WM_DESTROY:
                        u32.PostQuitMessage(0)
                        return 0
                except Exception as e:
                    logger.debug("wndproc error: %s", e)
                return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc = WNDPROC(wndproc)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinst
            wc.lpszClassName = self._class_name
            if not u32.RegisterClassW(ctypes.byref(wc)):
                raise OSError(f"RegisterClassW failed ({ctypes.get_last_error()})")

            hwnd = u32.CreateWindowExW(0, self._class_name, "MeowboardRawInput", 0, 0, 0, 0, 0,
                                       HWND_MESSAGE & ((1 << 64) - 1), None, hinst, None)
            if not hwnd:
                raise OSError(f"CreateWindowExW failed ({ctypes.get_last_error()})")
            self._hwnd = hwnd

            rid = RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, hwnd)  # generic desktop / keyboard
            if not u32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE)):
                raise OSError(f"RegisterRawInputDevices failed ({ctypes.get_last_error()})")
        except Exception as e:
            logger.error("Raw Input setup failed: %s", e)
            self._start_ok = False
            self._ready.set()
            self._cleanup_rawinput()
            return

        self._start_ok = True
        self._ready.set()
        try:
            msg = wintypes.MSG()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._cleanup_rawinput()
            self._is_running = False

    def _cleanup_rawinput(self):
        u32 = self._u32
        if u32 is None:
            return
        try:
            rid = RAWINPUTDEVICE(0x01, 0x06, RIDEV_REMOVE, None)
            u32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE))
        except Exception:
            pass
        try:
            if self._hwnd:
                u32.DestroyWindow(self._hwnd)
        except Exception:
            pass
        try:
            if self._class_name:
                u32.UnregisterClassW(self._class_name, ctypes.WinDLL("kernel32").GetModuleHandleW(None))
        except Exception:
            pass
        self._hwnd = None

    # ------------------------------------------------------------------ polling fallback

    def _poll_loop(self, down=None):
        get_state = self._get_async_key_state
        if down is None:
            down = set()
        while not self._stop_event.is_set():
            try:
                for vk in _WATCHED:
                    if get_state(vk) & 0x8000:
                        if vk not in down:
                            down.add(vk)
                            cb = self._on_key_down
                            if cb is not None:
                                try:
                                    cb(vk)
                                except Exception as e:
                                    logger.debug("on_key_down error: %s", e)
                    elif vk in down:
                        down.discard(vk)
            except Exception as e:
                logger.debug("Keyboard poll error: %s", e)
            self._stop_event.wait(POLL_INTERVAL_S)

    def _start_poll(self) -> bool:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            fn = user32.GetAsyncKeyState
            fn.argtypes = [ctypes.c_int]
            fn.restype = ctypes.c_short
            self._get_async_key_state = fn
        except Exception as e:
            logger.error("Could not bind GetAsyncKeyState: %s", e)
            return False
        self._stop_event.clear()
        # Seed synchronously so keys already held at start never fire, and none pressed after start are missed
        seed = {vk for vk in _WATCHED if fn(vk) & 0x8000}
        self._thread = threading.Thread(target=self._poll_loop, args=(seed,), name="MeowKeyPoller", daemon=True)
        self._thread.start()
        self.backend = "poll"
        return True

    # ------------------------------------------------------------------ public API

    def start(self) -> bool:
        if self._is_running:
            return True
        if sys.platform != "win32":
            logger.error("KeyboardListener is only supported on Windows")
            return False

        ok = False
        if self._requested_backend in ("auto", "rawinput"):
            self._ready.clear()
            self._thread = threading.Thread(target=self._rawinput_thread, name="MeowRawInput", daemon=True)
            self._thread.start()
            self._ready.wait(timeout=3.0)
            ok = self._start_ok
            if ok:
                self.backend = "rawinput"
            else:
                self._thread = None
        if not ok and self._requested_backend in ("auto", "poll"):
            logger.warning("Using polling fallback for keyboard observation")
            ok = self._start_poll()

        self._is_running = ok
        if ok:
            logger.info("Passive keyboard observer started (backend=%s, no hook installed)", self.backend)
        return ok

    def stop(self):
        """Stops observation. Idempotent; safe from any thread."""
        if not self._is_running and self._thread is None:
            return
        self._stop_event.set()
        if self.backend == "rawinput" and self._hwnd and self._u32:
            try:
                self._u32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.5)
        self._thread = None
        self._is_running = False
        logger.info("Passive keyboard observer stopped (seen=%d, ignored_injected=%d)", self.events_seen, self.events_ignored)

    @property
    def is_active(self) -> bool:
        return self._is_running
