"""Items 1, 3, 4: the system keyboard must work normally with MEOWBOARD enabled AND disabled."""
import time

import pytest
from PySide6.QtWidgets import QApplication

from audit import winio as w
from audit.harness import Harness

VK_CTRL, VK_SHIFT, VK_ALT, VK_TAB, VK_LWIN = 0xA2, 0xA0, 0xA4, 0x09, 0x5B
VK_A, VK_C, VK_V, VK_Z, VK_D, VK_F24, VK_END = 0x41, 0x43, 0x56, 0x5A, 0x44, 0x87, 0x23


def guard(h: Harness):
    """Never inject into anyone else's window."""
    assert w.fg() == h.hwnd, f"audit window lost focus (foreground is {w.window_title(w.fg())!r}); stopping"


@pytest.fixture(params=["enabled", "disabled"])
def app_running(request, harness):
    p, home = w.launch_app("source", enabled=(request.param == "enabled"))
    time.sleep(5.0)                       # let the real MEOWBOARD start and register for key events
    assert p.poll() is None, "MEOWBOARD exited on startup"
    harness.focus()
    yield request.param, p
    w.kill_tree(p)


def test_typing_and_modifiers_reach_the_focused_app(app_running, harness):
    mode, p = app_running
    harness.capture = False
    harness.edit.clear()
    guard(harness)
    for vk in [0x48, 0x45, 0x4C, 0x4C, 0x4F, 0x31, 0x32, 0x33]:     # H E L L O 1 2 3
        guard(harness)
        w.tap(vk)
        harness.pump(0.02)
    harness.pump(0.15)
    assert harness.edit.text().lower() == "hello123", f"[{mode}] typed {harness.edit.text()!r}"
    print(f"[{mode}] typed 'hello123' -> {harness.edit.text()!r}")

    harness.edit.clear()
    w.chord(VK_SHIFT, 0x41)
    harness.pump(0.1)
    assert harness.edit.text() == "A", f"Shift+A -> {harness.edit.text()!r}"
    w.tap(0x08)
    harness.pump(0.1)
    assert harness.edit.text() == ""
    for vk in (0x41, 0x42, 0x43):
        w.tap(vk)
    w.tap(0x25)
    w.tap(0x25)
    w.tap(0x58)
    harness.pump(0.15)   # A B C Left Left X
    assert harness.edit.text().lower() == "axbc", harness.edit.text()
    print(f"[{mode}] Shift, Backspace, arrow keys OK")


def test_function_navigation_numpad_keys_are_delivered(app_running, harness):
    mode, p = app_running
    guard(harness)
    harness.capture = True
    harness.downs.clear()
    keys = (list(range(0x70, 0x7C)) + [0x24, 0x23, 0x21, 0x22, 0x2D, 0x2E] + list(range(0x60, 0x6A))
            + [0x1B, 0x09, 0x20, 0x0D])
    for vk in keys:
        guard(harness)
        w.tap(vk)
        harness.pump(0.012)
    harness.pump(0.2)
    harness.capture = False
    got = set(harness.downs)
    missing = [hex(k) for k in keys if k not in got]
    print(f"[{mode}] F1-F12, nav, numpad, Esc/Tab/Space/Enter: delivered {len(keys) - len(missing)}/{len(keys)}")
    assert not missing, f"[{mode}] keys never reached the application: {missing}"


def test_ctrl_c_v_z_work(app_running, harness):
    mode, p = app_running
    guard(harness)
    cb = QApplication.clipboard()
    cb.setText("")
    harness.capture = False
    harness.edit.setText("cat")
    harness.pump(0.1)
    w.chord(VK_CTRL, VK_A)
    harness.pump(0.1)
    w.chord(VK_CTRL, VK_C)
    harness.pump(0.2)
    assert cb.text() == "cat", f"[{mode}] Ctrl+C -> clipboard {cb.text()!r}"
    w.tap(VK_END)
    harness.pump(0.05)
    w.chord(VK_CTRL, VK_V)
    harness.pump(0.2)
    assert harness.edit.text() == "catcat", f"[{mode}] Ctrl+V -> {harness.edit.text()!r}"
    w.chord(VK_CTRL, VK_Z)
    harness.pump(0.2)
    assert harness.edit.text() == "cat", f"[{mode}] Ctrl+Z -> {harness.edit.text()!r}"
    print(f"[{mode}] Ctrl+C / Ctrl+V / Ctrl+Z all behaved normally")


def _alt_tab():
    w.send([(VK_ALT, False)])
    time.sleep(0.1)
    w.send([(VK_TAB, False)])
    time.sleep(0.05)
    w.send([(VK_TAB, True)])
    time.sleep(0.5)
    w.send([(VK_ALT, True)])
    time.sleep(0.8)


def test_alt_tab_switches_windows_and_back(app_running, harness):
    mode, p = app_running
    guard(harness)
    start = w.fg()
    _alt_tab()
    after = w.fg()
    print(f"[{mode}] Alt+Tab: {w.window_title(start)!r} -> {w.window_title(after)!r}")
    if after == start:
        pytest.skip("only one switchable window on this desktop; Alt+Tab has nowhere to go")
    _alt_tab()
    harness.focus()
    assert w.fg() == harness.hwnd


def test_win_d_and_empty_desktop_keyboard(app_running, harness):
    """Win+D shows the empty desktop; keys must still be seen there; Win+D restores."""
    mode, p = app_running
    guard(harness)
    w.chord(VK_LWIN, VK_D, hold=0.08)
    time.sleep(1.2)
    harness.pump(0.1)
    cls = w.window_class(w.fg())
    iconic = bool(w.user32.IsIconic(harness.hwnd))
    print(f"[{mode}] after Win+D: foreground class={cls!r}, audit window minimized={iconic}")
    try:
        assert iconic or cls in ("Progman", "WorkerW", "Shell_TrayWnd"), "Win+D did not show the desktop"
        w.send([(VK_F24, False)])
        time.sleep(0.05)
        down = w.key_is_down(VK_F24)
        w.send([(VK_F24, True)])
        print(f"[{mode}] empty desktop: F24 key state seen = {down}")
        assert down, "keyboard input not registered on the empty desktop"
    finally:
        w.chord(VK_LWIN, VK_D, hold=0.08)
        time.sleep(1.2)
        harness.focus()
    assert not w.user32.IsIconic(harness.hwnd), "Win+D did not restore windows"
    guard(harness)
