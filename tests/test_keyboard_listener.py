"""Tests for the passive KeyboardListener."""
import time
from pathlib import Path

from meowboard.core import keyboard_listener as kl
from meowboard.core.keyboard_listener import KeyboardListener


def test_keyboard_listener_lifecycle():
    listener = KeyboardListener(on_key_down=lambda vk: None)
    assert not listener.is_active
    assert listener.start()
    assert listener.is_active
    time.sleep(0.1)
    listener.stop()
    assert not listener.is_active
    listener.stop()  # idempotent


def test_detects_key_down_edges_only():
    state = {0x41: 0}
    events = []
    listener = KeyboardListener(on_key_down=events.append)
    listener._get_async_key_state = lambda vk: state.get(vk, 0)
    listener._stop_event.clear()
    import threading
    t = threading.Thread(target=listener._poll_loop, daemon=True)
    t.start()
    time.sleep(0.03)
    state[0x41] = -32768  # pressed (0x8000)
    time.sleep(0.05)      # held: must fire exactly once
    state[0x41] = 0
    time.sleep(0.03)
    state[0x41] = -32768
    time.sleep(0.03)
    listener._stop_event.set()
    t.join(1)
    assert events == [0x41, 0x41]
