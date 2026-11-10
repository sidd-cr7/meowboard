"""Manual physical-keyboard probe. Run it, type on your real keyboard, press Esc x3 to quit.
Shows each key-down the passive listener sees (including key-repeat). It cannot affect typing."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from meowboard.core.keyboard_listener import KeyboardListener
from meowboard.core.pitch_mapper import PitchMapper

pm = PitchMapper()
esc = []
def on_key(vk):
    print(f"{pm.get_key_profile(vk).name:>10}  vk=0x{vk:02X}", flush=True)
    esc.append(vk) if vk == 0x1B else esc.clear()

l = KeyboardListener(on_key_down=on_key, ignore_injected=False)
print("backend:", l.start() and l.backend, "- type anywhere; Esc x3 to quit")
try:
    while len(esc) < 3:
        time.sleep(0.05)
finally:
    l.stop()
