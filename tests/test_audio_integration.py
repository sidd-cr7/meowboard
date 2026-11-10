"""Audio integration tests: real recordings, loudness, pitch, channel pool, bounds, stop, fallbacks."""
import os
import shutil
import time
from pathlib import Path

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")  # silent, deterministic

import numpy as np
import pytest

from meowboard.config.settings import INTENSITY_CHANNELS, PERSONALITIES
from meowboard.core import audio_engine as ae
from meowboard.core.audio_engine import AudioEngine
from meowboard.core.pitch_mapper import SOUND_CATEGORIES
from meowboard.core.sound_manager import (
    CATEGORIES, PEAK_CEILING, SoundManager, normalize_loudness, pitch_shift, slug,
)

REAL_SOUNDS = Path(__file__).resolve().parent.parent / "meowboard" / "assets" / "sounds"
SR = 44100


@pytest.fixture(scope="module")
def mgr():
    return SoundManager(assets_dir=REAL_SOUNDS)


def make_engine(mgr, mode):
    return AudioEngine(sound_manager=mgr, intensity=mode, volume=80, enabled=True)


def long_sound(seconds=3.0):
    import pygame
    n = int(SR * seconds)
    t = np.arange(n) / SR
    mono = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
    return pygame.mixer.Sound(buffer=np.column_stack((mono, mono)).tobytes())


# 1 + 2: real recordings, all categories
def test_all_real_recordings_loaded(mgr):
    assert mgr.missing_assets == {}
    for p in PERSONALITIES:
        for c in CATEGORIES:
            assert (REAL_SOUNDS / slug(p) / f"{c}.wav").exists()
            pcm, sr = mgr._raw_samples[p][c]
            assert sr == SR and pcm.ndim == 2 and pcm.shape[1] == 2 and len(pcm) > SR * 0.2


# 4: loudness
def test_loudness_is_normalized_and_never_clips(mgr):
    rms = []
    for p in PERSONALITIES:
        for c in CATEGORIES:
            pcm = mgr._raw_samples[p][c][0].astype(np.float32)
            assert np.abs(pcm).max() <= PEAK_CEILING + 1
            rms.append(20 * np.log10(np.sqrt((pcm ** 2).mean())))
    spread = max(rms) - min(rms)
    print(f"RMS spread across 20 samples: {spread:.2f} dB")
    assert spread < 2.5  # raw files spanned ~9.6 dB


def test_normalize_loudness_respects_peak():
    x = np.zeros((1000, 2), dtype=np.int16)
    x[0] = 30000  # very peaky, low RMS
    y = normalize_loudness(x)
    assert np.abs(y.astype(int)).max() <= 32767 and np.abs(y).max() <= PEAK_CEILING + 1


# 3: pitch shift preserves duration and shifts frequency
@pytest.mark.parametrize("ratio", [0.88, 0.95, 1.08, 1.2])
def test_pitch_shift_keeps_duration_and_moves_pitch(ratio):
    n = SR
    t = np.arange(n) / SR
    mono = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
    out = pitch_shift(np.column_stack((mono, mono)), ratio)
    assert abs(len(out) - n) <= 1, "duration (playback speed) must not change"
    seg = out[SR // 4: 3 * SR // 4, 0].astype(np.float32)
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    freq = np.argmax(spec) * SR / len(seg)
    print(f"ratio {ratio}: 440 Hz -> {freq:.1f} Hz (expected {440 * ratio:.1f})")
    assert abs(freq / (440 * ratio) - 1) < 0.03


def test_real_clip_variants_same_length_no_clipping(mgr):
    pcm = mgr._raw_samples["NORMAL CAT"]["standard"][0]
    for ratio in (0.88, 1.0, 1.2):
        out = pitch_shift(pcm, ratio)
        assert abs(len(out) - len(pcm)) <= 1
        assert np.abs(out.astype(int)).max() < 32767
        assert np.sqrt((out.astype(np.float32) ** 2).mean()) > 1000  # not silent / mangled


# 1: everything preloaded, lookup is pure memory
def test_all_personalities_preloaded_and_lookup_fast(mgr):
    for p in PERSONALITIES:
        mgr.preload_personality(p)
        assert set(mgr._sound_cache[p]) == set(SOUND_CATEGORIES)
    t0 = time.perf_counter()
    for i in range(2000):
        mgr.get_sound_for_key(0x41 + i % 26)
    per_call_us = (time.perf_counter() - t0) / 2000 * 1e6
    print(f"get_sound_for_key: {per_call_us:.1f} us/call")
    assert per_call_us < 500


# 5 + 6: channel pool 4/12/24, bounded
@pytest.mark.parametrize("mode", ["CHILL", "NORMAL", "CHAOS"])
def test_channel_pool_limits(mgr, mode):
    limit = INTENSITY_CHANNELS[mode]
    engine = make_engine(mgr, mode)
    try:
        snd = long_sound()
        for _ in range(limit * 2):
            engine.trigger_sound(snd, 0.5)
            time.sleep(0.004)
        time.sleep(0.2)
        print(f"{mode}: limit={limit} active={engine.active_channels}")
        assert engine.active_channels == limit
        busy_total = sum(1 for ch in engine._channels if ch.get_busy())
        assert busy_total == limit, "no channel beyond the pool limit may play"
    finally:
        engine.shutdown()


# 9: newest-event priority
def test_newest_event_wins_when_saturated(mgr):
    import pygame
    engine = make_engine(mgr, "CHILL")
    try:
        sounds = [long_sound(2.0 + i * 0.1) for i in range(8)]
        for s in sounds:
            engine.trigger_sound(s, 0.5)
            time.sleep(0.01)
        time.sleep(0.2)
        playing = [ch.get_sound() for ch in engine._channels[:4] if ch.get_busy()]
        assert len(playing) == 4
        assert sounds[-1] in playing, "most recent event must be audible"
        assert sounds[0] not in playing, "oldest must have been stolen"
    finally:
        engine.shutdown()


# 7: bounded queue
def test_queue_is_bounded_under_flood(mgr):
    engine = make_engine(mgr, "CHAOS")
    try:
        with engine._lock:  # stall the worker's playback
            max_pending = 0
            for i in range(5000):
                engine.trigger_key(0x41 + i % 26)
                max_pending = max(max_pending, engine.pending_events)
        print(f"max pending during 5000-event flood: {max_pending}")
        assert max_pending <= ae.QUEUE_MAX
    finally:
        engine.shutdown()


# 8: delayed sounds do not accumulate
def test_stale_events_are_dropped_not_played_late(mgr):
    engine = make_engine(mgr, "NORMAL")
    played = []
    engine._on_key_played = lambda prof: played.append(prof.name)
    try:
        with engine._lock:
            for i in range(20):
                engine.trigger_key(0x41 + i)
            time.sleep(0.35)  # worker is stuck; events age past MAX_EVENT_AGE_S
        time.sleep(0.4)
        print(f"played={len(played)} dropped_stale={engine._dropped_stale} pending={engine.pending_events}")
        assert engine._dropped_stale >= 15
        assert len(played) <= 5
        assert engine.pending_events == 0
    finally:
        engine.shutdown()


# 10: immediate stop
def test_stop_all_is_immediate(mgr):
    engine = make_engine(mgr, "CHAOS")
    try:
        snd = long_sound()
        for _ in range(24):
            engine.trigger_sound(snd, 0.5)
        time.sleep(0.15)
        assert engine.active_channels > 0
        t0 = time.perf_counter()
        engine.stop_all()
        ms = (time.perf_counter() - t0) * 1000
        print(f"stop_all took {ms:.2f} ms")
        assert engine.active_channels == 0 and engine.pending_events == 0
        assert ms < 50
    finally:
        engine.shutdown()


# 12: playback requests never block the caller
def test_trigger_does_not_block_caller(mgr):
    engine = make_engine(mgr, "CHAOS")
    try:
        with engine._lock:  # even with audio thread wedged
            t0 = time.perf_counter()
            for i in range(1000):
                engine.trigger_key(0x41 + i % 26)
            per_call_us = (time.perf_counter() - t0) / 1000 * 1e6
        print(f"trigger_key (audio thread wedged): {per_call_us:.1f} us/call")
        assert per_call_us < 200
    finally:
        engine.shutdown()


# 11: missing assets
def test_missing_directory_falls_back_without_crashing(tmp_path):
    m = SoundManager(assets_dir=tmp_path / "does_not_exist")
    assert len(m.missing_assets) == 20
    snd, prof = m.get_sound_for_key(0x41)
    assert snd is not None
    eng = AudioEngine(sound_manager=m, intensity="CHILL", volume=50, enabled=True)
    try:
        eng.trigger_key(0x20)
        time.sleep(0.2)
        assert eng.pending_events == 0
    finally:
        eng.shutdown()


def test_partial_and_corrupt_assets_fall_back(tmp_path):
    src = REAL_SOUNDS / "normal_cat"
    dst = tmp_path / "normal_cat"
    dst.mkdir()
    shutil.copy(src / "standard.wav", dst / "standard.wav")
    (dst / "space.wav").write_bytes(b"this is not a wav file")
    m = SoundManager(assets_dir=tmp_path)
    assert ("NORMAL CAT", "space") in m.missing_assets      # corrupt
    assert ("KITTEN", "standard") in m.missing_assets       # absent
    for p in PERSONALITIES:
        for c in CATEGORIES:
            assert c in m._raw_samples[p], f"no fallback for {p}/{c}"
    for vk in (0x20, 0x0D, 0x08, 0x1B, 0x41):
        assert m.get_sound_for_key(vk)[0] is not None


def test_engine_survives_no_sound_manager():
    eng = AudioEngine(sound_manager=None, intensity="CHILL", volume=50, enabled=True)
    try:
        eng.trigger_key(0x41)
        time.sleep(0.1)
        eng.stop_all()
    finally:
        eng.shutdown()
