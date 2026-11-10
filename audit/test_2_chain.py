"""
Items 2, 5-11, 15: the full chain  real injected key -> Raw Input listener -> engine -> played meow.
Audio device is the dummy driver here (silent); everything else is the real code path.
"""
import threading
import time
from collections import Counter

import pytest

from audit import winio as w
from audit.harness import Harness
from meowboard.config.settings import INTENSITY_CHANNELS, PERSONALITIES
from meowboard.core import audio_engine as ae
from meowboard.core.audio_engine import AudioEngine
from meowboard.core.keyboard_listener import KeyboardListener
from meowboard.core.pitch_mapper import PitchMapper
from meowboard.core.sound_manager import SoundManager

ROOT = w.ROOT

LETTERS = list(range(0x41, 0x5B))
DIGITS = list(range(0x30, 0x3A))
PUNCT = [0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE]
FKEYS = list(range(0x70, 0x88))
EDIT = [0x1B, 0x09, 0x0D, 0x08, 0x20, 0x13]
MODS = [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5]
NAV = [0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28]
NUMPAD = list(range(0x60, 0x70))
LOCKS = [0x14, 0x90, 0x91]          # toggled twice (net zero) and verified restored
INJECTABLE = LETTERS + DIGITS + PUNCT + FKEYS + EDIT + MODS + NAV + NUMPAD + LOCKS
# Deliberately NOT injected (they would act on the user's session): Win keys, Apps, PrtSc, Sleep,
# media/browser/launch keys, IME and exotic OEM keys.


class Stack:
    """Real listener + engine + sound manager, with instrumentation."""

    def __init__(self, mgr):
        self.mgr = mgr
        self.engine = AudioEngine(sound_manager=mgr, intensity="NORMAL", volume=60, enabled=True)
        self.played = []          # (perf_counter, vk, name)
        self.heard = []           # listener callbacks: (perf_counter, vk)
        self.engine._on_key_played = lambda prof: self.played.append((time.perf_counter(), prof.vk_code, prof.name))
        self.listener = KeyboardListener(on_key_down=self._on_key, ignore_injected=False)
        assert self.listener.start() and self.listener.backend == "rawinput"
        self.max_busy = 0
        self.max_pending = 0
        self._mon_stop = threading.Event()
        self._mon = threading.Thread(target=self._monitor, daemon=True)
        self._mon.start()

    def _on_key(self, vk):
        self.heard.append((time.perf_counter(), vk))
        self.engine.trigger_key(vk)

    def _monitor(self):
        while not self._mon_stop.is_set():
            try:
                busy = sum(1 for c in self.engine._channels if c.get_busy())
                self.max_busy = max(self.max_busy, busy)
                self.max_pending = max(self.max_pending, self.engine.pending_events)
            except Exception:
                pass
            time.sleep(0.001)

    def reset(self):
        self.played.clear()
        self.heard.clear()
        self.max_busy = 0
        self.max_pending = 0

    def close(self):
        self._mon_stop.set()
        self.listener.stop()
        self.engine.shutdown()


@pytest.fixture(scope="module")
def stack(harness):
    import pygame
    mgr = SoundManager(assets_dir=ROOT / "meowboard" / "assets" / "sounds")
    s = Stack(mgr)
    for p in PERSONALITIES:
        mgr.preload_personality(p)
    assert harness.focus()
    harness.capture = True
    yield s
    harness.capture = False
    s.close()


def guard(h):
    assert w.fg() == h.hwnd, f"audit window lost focus ({w.window_title(w.fg())!r}); stopping"


def burst(vks, up_delay=False):
    ev = []
    for vk in vks:
        ev += [(vk, False), (vk, True)]
    w.send(ev)


# ---------------------------------------------------------------- 2. every supported key triggers a meow
def test_every_supported_key_triggers_a_meow(stack, harness):
    s = stack
    s.engine.set_intensity("CHAOS")
    toggle_before = {vk: w.toggled(vk) for vk in LOCKS}
    failed = []
    for vk in INJECTABLE:
        guard(harness)
        s.reset()
        w.tap(vk)
        if vk in LOCKS:
            time.sleep(0.05)
            w.tap(vk)                      # second press restores the lock state
        end = time.time() + 1.0
        want = 2 if vk in LOCKS else 1
        while time.time() < end and sum(1 for _, v, _ in s.played if v == vk) < want:
            harness.pump(0.005)
        got = sum(1 for _, v, _ in s.played if v == vk)
        if got < want:
            failed.append((hex(vk), got))
        time.sleep(0.03)
    for vk in LOCKS:
        assert w.toggled(vk) == toggle_before[vk], f"lock key {hex(vk)} state not restored"
    print(f"injected {len(INJECTABLE)} distinct physical keys; meows missing for: {failed or 'none'}")
    assert not failed, failed


# ---------------------------------------------------------------- 5. rapid typing, no backlog
def test_rapid_typing_has_low_latency_and_no_backlog(stack, harness):
    s = stack
    s.engine.set_intensity("NORMAL")
    guard(harness)
    s.reset()
    keys = (LETTERS * 5)[:75]              # 75 keys at ~15 keys/s (very fast typist) = 5 s
    for vk in keys:
        guard(harness)
        w.tap(vk)
        time.sleep(1 / 15)
    time.sleep(0.4)
    assert len(s.played) == len(s.heard) == len(keys), (len(keys), len(s.heard), len(s.played))
    lat = sorted((p[0] - h[0]) * 1000 for h, p in zip(s.heard, s.played))
    p50, p95, mx = lat[len(lat) // 2], lat[int(len(lat) * .95)], lat[-1]
    print(f"15 keys/s: {len(keys)} keys -> {len(s.played)} meows, latency listener->play p50={p50:.1f}ms p95={p95:.1f}ms max={mx:.1f}ms")
    assert mx < 60
    assert s.engine.pending_events == 0


def test_flood_leaves_no_delayed_audio_backlog(stack, harness):
    s = stack
    s.engine.set_intensity("NORMAL")
    guard(harness)
    s.reset()
    n = 400
    t0 = time.perf_counter()
    burst([LETTERS[i % 26] for i in range(n)])       # 800 events in one call, ~instantaneous
    t_inject = time.perf_counter() - t0
    # wait until the keyboard side has seen everything
    end = time.time() + 3
    while time.time() < end and len(s.heard) < n:
        harness.pump(0.005)
    last_heard = s.heard[-1][0]
    time.sleep(0.5)
    last_played = s.played[-1][0] if s.played else 0
    drain_ms = (last_played - last_heard) * 1000
    print(f"flood: injected {n} keys in {t_inject * 1000:.0f} ms; listener saw {len(s.heard)}; "
          f"played {len(s.played)}; dropped(oldest-first) {s.engine.dropped_events}; "
          f"max pending {s.max_pending}; last meow {drain_ms:.1f} ms after last key")
    assert len(s.heard) == n, "listener must observe every key-down"
    assert s.max_pending <= ae.QUEUE_MAX
    assert s.engine.pending_events == 0
    assert drain_ms < 150, "audio kept playing events long after the keys: backlog"
    time.sleep(0.3)
    played_after = len(s.played)
    time.sleep(0.5)
    assert len(s.played) == played_after, "late sounds still being produced"


# ---------------------------------------------------------------- 6 + 7. channel limits, all intensity modes
@pytest.mark.parametrize("mode", ["CHILL", "NORMAL", "CHAOS"])
def test_channels_never_exceed_limit_in_each_mode(stack, harness, mode):
    s = stack
    limit = INTENSITY_CHANNELS[mode]
    s.engine.set_intensity(mode)
    time.sleep(0.8)
    guard(harness)
    s.reset()
    for _ in range(3):
        burst([LETTERS[i % 26] for i in range(120)])
        time.sleep(0.12)
    time.sleep(0.5)
    print(f"{mode}: configured limit={limit} max simultaneously playing (all 24 channels sampled @1ms)={s.max_busy}")
    assert 0 < s.max_busy <= limit
    assert s.max_busy >= min(limit, 3), "mode never actually used its channels"
    time.sleep(1.6)


# ---------------------------------------------------------------- 8 + 9. personalities, pitch differences
def _locate(mgr, personality, sound):
    for cat, buckets in mgr._sound_cache[personality].items():
        for bucket, variants in buckets.items():
            for v in variants:
                if v is sound:
                    return cat, bucket
    return None, None


def _tap_and_locate(s, harness, vk, personality):
    s.reset()
    w.tap(vk)
    time.sleep(0.06)
    found = []
    for c in s.engine._channels:
        if c.get_busy():
            snd = c.get_sound()
            if snd is not None:
                found.append(snd)
    s.engine.stop_all()
    time.sleep(0.02)
    for snd in found:
        cat, bucket = _locate(s.mgr, personality, snd)
        if cat:
            return cat, bucket, snd
    return None, None, None


@pytest.mark.parametrize("personality", PERSONALITIES)
def test_each_personality_plays_its_own_sounds_with_pitch_spread(stack, harness, personality):
    s = stack
    s.engine.set_intensity("CHAOS")
    s.engine.set_personality(personality)
    guard(harness)
    others = [p for p in PERSONALITIES if p != personality]
    row = [0x51, 0x57, 0x45, 0x52, 0x54, 0x59, 0x55, 0x49, 0x4F, 0x50]      # Q..P
    buckets = []
    for vk in row:
        cat, bucket, snd = _tap_and_locate(s, harness, vk, personality)
        assert cat == "standard", f"{personality}/{hex(vk)} played from {cat}"
        for o in others:
            assert _locate(s.mgr, o, snd)[0] is None, f"{personality} played a {o} sample"
        buckets.append(bucket)
    expect = [s.mgr._pitch_mapper.pitch_for(vk, personality) for vk in row]
    print(f"{personality}: Q..P buckets played = {buckets}  (mapper pitch {expect[0]:.3f}..{expect[-1]:.3f})")
    assert len(set(buckets)) >= 4, "adjacent keys should land on several distinct (but close) pitches"
    assert max(buckets) - min(buckets) <= 0.13, "pitch differences must stay subtle"
    assert all(abs(b - e) <= 0.016 for b, e in zip(buckets, expect)), "played bucket must follow the key's mapped pitch"
    # direction of the contour differs per personality (angry descends left->right)
    slope_up = buckets[-1] >= buckets[0]
    assert slope_up == (personality != "ANGRY CAT")


def test_special_keys_use_their_own_samples(stack, harness):
    s = stack
    s.engine.set_personality("NORMAL CAT")
    guard(harness)
    cats = {}
    for name, vk in {"space": 0x20, "enter": 0x0D, "backspace": 0x08, "escape": 0x1B, "F5": 0x74, "ctrl": 0xA2, "left": 0x25}.items():
        cat, bucket, _ = _tap_and_locate(s, harness, vk, "NORMAL CAT")
        cats[name] = cat
    print("special keys ->", cats)
    assert cats == {"space": "space", "enter": "enter", "backspace": "backspace", "escape": "escape",
                    "F5": "function", "ctrl": "modifier", "left": "nav"}


# ---------------------------------------------------------------- 10. hold = repeated meows
def test_holding_a_key_repeats_meows(stack, harness):
    s = stack
    s.engine.set_intensity("NORMAL")
    guard(harness)
    s.reset()
    # Windows typematic: one initial key-down, then repeated key-downs while held, one key-up at the end
    w.send([(0x48, False)])
    time.sleep(0.5)
    for _ in range(15):
        w.send([(0x48, False)])
        time.sleep(0.033)
    w.send([(0x48, True)])
    time.sleep(0.3)
    n = Counter(v for _, v, _ in s.played)[0x48]
    print(f"held H: 1 initial + 15 repeats injected -> listener saw {sum(1 for _, v in s.heard if v == 0x48)}, meows played {n}")
    assert n == 16


# ---------------------------------------------------------------- 11. ON/OFF immediate
def test_off_is_immediate_and_on_resumes(stack, harness):
    s = stack
    s.engine.set_intensity("CHAOS")
    guard(harness)
    s.reset()
    burst([LETTERS[i % 26] for i in range(60)])
    time.sleep(0.15)
    assert s.max_busy > 0
    t0 = time.perf_counter()
    s.engine.set_enabled(False)
    busy_now = sum(1 for c in s.engine._channels if c.get_busy())
    ms = (time.perf_counter() - t0) * 1000
    print(f"OFF while {s.max_busy} channels were playing -> {busy_now} playing {ms:.2f} ms later, pending={s.engine.pending_events}")
    assert busy_now == 0 and s.engine.pending_events == 0 and ms < 50
    s.reset()
    for vk in (0x41, 0x42, 0x43):
        w.tap(vk)
        time.sleep(0.05)
    time.sleep(0.2)
    assert len(s.heard) == 3 and len(s.played) == 0 and s.max_busy == 0, "keys still seen but silent while OFF"
    s.engine.set_enabled(True)
    s.reset()
    w.tap(0x41)
    time.sleep(0.2)
    assert len(s.played) == 1
    time.sleep(1.0)


# ---------------------------------------------------------------- 15. audio device loss
class _DeadChannel:
    def get_busy(self):
        return False

    def play(self, *a, **k):
        raise RuntimeError("audio device lost")

    def stop(self):
        pass

    def set_volume(self, *a):
        pass

    def get_sound(self):
        return None


def test_audio_device_failure_is_handled_and_recovers(stack, harness):
    s = stack
    s.engine.set_enabled(True)
    s.engine.set_intensity("NORMAL")
    guard(harness)
    s.engine._last_recovery = 0.0
    real = s.engine._channels
    s.engine._channels = [_DeadChannel() for _ in real]     # every playback now raises, like a vanished device
    s.reset()
    w.tap(0x41)                                               # keyboard must stay fully functional meanwhile
    harness.pump(0.2)
    assert w.fg() == harness.hwnd
    t0 = time.time()
    while time.time() < t0 + 30 and not (s.engine.is_healthy and s.engine._channels is not real
                                         and not isinstance(s.engine._channels[0], _DeadChannel)):
        harness.pump(0.1)
        w.tap(0x42)                                           # user keeps typing during the outage
    recovered = time.time() - t0
    print(f"device failure injected; keyboard events seen during outage: {len(s.heard)}; "
          f"engine healthy again after {recovered:.1f}s")
    assert s.engine.is_healthy and not isinstance(s.engine._channels[0], _DeadChannel)
    s.reset()
    w.tap(0x43)
    time.sleep(0.3)
    assert [v for _, v, _ in s.played] == [0x43], "meows must resume after recovery"
    time.sleep(1.0)


def test_mixer_torn_down_under_load_does_not_crash_or_hang(stack, harness):
    import pygame
    s = stack
    guard(harness)
    s.engine._last_recovery = 0.0
    with s.engine._lock:
        pygame.mixer.quit()                 # as if the device/driver went away
    s.reset()
    for vk in (0x41, 0x42, 0x43, 0x44):
        w.tap(vk)
        harness.pump(0.05)
    assert w.fg() == harness.hwnd
    t0 = time.time()
    while time.time() < t0 + 30 and not s.engine.is_healthy:
        harness.pump(0.1)
    print(f"mixer torn down; healthy again after {time.time() - t0:.1f}s; keys heard during outage: {len(s.heard)}")
    assert len(s.heard) == 4, "listener must keep observing keys during an audio outage"
    assert s.engine.is_healthy
    s.reset()
    w.tap(0x45)
    time.sleep(0.3)
    assert len(s.played) == 1
