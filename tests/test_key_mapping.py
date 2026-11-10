"""Key-to-pitch mapping tests: coverage of every physical key, regions, subtlety, randomness, personalities."""
import math
import os
from pathlib import Path

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pytest

from meowboard.config.settings import (
    PERSONALITIES, PERSONALITY_MAPPING, PITCH_MAX, PITCH_MIN, REGION_DEFAULT, REGION_NUMPAD,
)
from meowboard.core.audio_engine import AudioEngine
from meowboard.core.pitch_mapper import SOUND_CATEGORIES, PitchMapper
from meowboard.core.sound_manager import SoundManager

SOUNDS = Path(__file__).resolve().parent.parent / "meowboard" / "assets" / "sounds"

# --- an independent list of every physical key (NOT derived from the mapper) ---
LETTERS = list(range(0x41, 0x5B))
DIGITS = list(range(0x30, 0x3A))
FKEYS = list(range(0x70, 0x88))                              # F1..F24
OEM = [0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF, 0xE2]
EDIT = [0x1B, 0x09, 0x14, 0x0D, 0x08, 0x20]
MODS = [0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x5D]
NAV = [0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x91, 0x13]
NUMPAD = list(range(0x60, 0x70)) + [0x90, 0x0C]
MEDIA = list(range(0xA6, 0xB8))
ALL_PHYSICAL = LETTERS + DIGITS + FKEYS + OEM + EDIT + MODS + NAV + NUMPAD + MEDIA


@pytest.fixture(scope="module")
def mapper():
    return PitchMapper(pitch_randomness=0.0)


@pytest.fixture(scope="module")
def mgr():
    import pygame
    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.mixer.init()
    m = SoundManager(assets_dir=SOUNDS)
    for p in PERSONALITIES:
        m.preload_personality(p)
    return m


def semitones(r):
    return 12 * math.log2(r)


# 1: every physical key has a valid mapping (no fallback used)
def test_every_physical_key_has_a_real_mapping(mapper):
    missing = [hex(v) for v in ALL_PHYSICAL if v not in mapper._key_map]
    assert not missing, f"unmapped physical keys: {missing}"
    print(f"{len(ALL_PHYSICAL)} physical keys checked, {len(mapper.supported_vks())} mapped")


@pytest.mark.parametrize("personality", PERSONALITIES)
def test_every_key_has_valid_pitch_category_region_per_personality(mapper, personality):
    for vk in mapper.supported_vks():
        prof = mapper.get_key_profile(vk)
        pitch = mapper.pitch_for(vk, personality)
        assert PITCH_MIN <= pitch <= PITCH_MAX, (prof.name, pitch)
        assert prof.sound_category in SOUND_CATEGORIES
        assert prof.name and prof.region
        _, cat, _ = mapper.get_pitch_for_key(vk, personality)
        assert cat == prof.sound_category


def test_any_vk_code_never_raises_and_stays_in_bounds(mapper):
    for vk in range(0, 300):
        pitch, cat, prof = mapper.get_pitch_for_key(vk)
        assert PITCH_MIN <= pitch <= PITCH_MAX and cat in SOUND_CATEGORIES


# 1b: every key actually yields a playable sound for every personality
@pytest.mark.parametrize("personality", PERSONALITIES)
def test_every_key_yields_a_playable_sound(mgr, mapper, personality):
    mgr.set_personality(personality)
    for vk in list(mapper.supported_vks()) + [0xE8, 0xFE, 0x00]:
        snd, prof = mgr.get_sound_for_key(vk)
        assert snd is not None and hasattr(snd, "play"), f"{prof.name} has no sound ({personality})"


# 2 + 3 + 4: regions, subtle adjacent differences, small intervals
def test_region_ordering_matches_spec(mapper):
    def avg(vks):
        return sum(mapper.pitch_for(v) for v in vks) / len(vks)
    fn, num, qw = avg(range(0x70, 0x7C)), avg(DIGITS), avg([0x51, 0x57, 0x45, 0x52, 0x54, 0x59, 0x55, 0x49, 0x4F, 0x50])
    asdf = avg([0x41, 0x53, 0x44, 0x46, 0x47, 0x48, 0x4A, 0x4B, 0x4C])
    zxcv = avg([0x5A, 0x58, 0x43, 0x56, 0x42, 0x4E, 0x4D])
    pad = avg(range(0x60, 0x6A))
    print(f"fn={fn:.3f} num={num:.3f} qwerty={qw:.3f} asdf={asdf:.3f} zxcv={zxcv:.3f} numpad={pad:.3f}")
    assert fn > num > qw > asdf > zxcv
    assert 1.02 < num < 1.12            # medium to slightly high
    assert 0.99 < qw < 1.06             # medium
    assert 0.94 < asdf < 1.0            # medium to slightly low
    assert 0.88 <= zxcv < 0.96          # low to medium
    assert 1.02 < pad < 1.10            # medium to slightly high


def test_adjacent_keys_differ_very_subtly(mapper):
    rows = [
        [0x51, 0x57, 0x45, 0x52, 0x54, 0x59, 0x55, 0x49, 0x4F, 0x50],
        [0x41, 0x53, 0x44, 0x46, 0x47, 0x48, 0x4A, 0x4B, 0x4C],
        [0x5A, 0x58, 0x43, 0x56, 0x42, 0x4E, 0x4D],
        [0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x30],
        list(range(0x70, 0x7C)),
    ]
    diffs = []
    for row in rows:
        for a, b in zip(row, row[1:]):
            d = abs(mapper.pitch_for(a) - mapper.pitch_for(b))
            diffs.append(d)
            assert d <= 0.012, "adjacent keys must differ by only a hair"
    assert all(d > 0 for d in diffs), "but adjacent keys should not be exactly identical"
    print(f"adjacent-key pitch step: min={min(diffs):.4f} max={max(diffs):.4f} "
          f"(~{semitones(1 + max(diffs)) * 100:.0f} cents max)")


def test_all_intervals_are_small(mapper):
    for p in PERSONALITIES:
        ps = [mapper.pitch_for(v, p) for v in mapper.supported_vks()]
        lo, hi = semitones(min(ps)), semitones(max(ps))
        print(f"{p}: {lo:+.2f} .. {hi:+.2f} semitones")
        assert lo >= -2.3 and hi <= 3.2


# 6 + 7: controlled randomness and non-identical repeats
def test_pitch_jitter_is_small_and_nonzero():
    m = PitchMapper()   # default jitter
    base = m.pitch_for(0x41)
    vals = {m.get_pitch_for_key(0x41)[0] for _ in range(300)}
    assert len(vals) > 20
    assert max(abs(v - base) for v in vals) <= 0.0045
    assert len({PitchMapper(pitch_randomness=0.0).get_pitch_for_key(0x41)[0] for _ in range(20)}) == 1


def test_repeated_presses_of_same_key_are_not_identical(mgr):
    mgr.set_personality("NORMAL CAT")
    sounds = [mgr.get_sound_for_key(0x41)[0] for _ in range(60)]
    assert all(a is not b for a, b in zip(sounds, sounds[1:])), "same rendition twice in a row"
    raw = {bytes(s.get_raw()[:20000]) for s in sounds}
    assert len(raw) >= 3, "should cycle through several distinct renditions"


# 8: personalities map differently
def test_personalities_have_different_mappings(mapper):
    keys = [0x41, 0x51, 0x5A, 0x31, 0x70, 0x20]
    tables = {p: tuple(mapper.pitch_for(k, p) for k in keys) for p in PERSONALITIES}
    assert len(set(tables.values())) == 4
    mean = {p: np.mean([mapper.pitch_for(v, p) for v in LETTERS]) for p in PERSONALITIES}
    assert mean["KITTEN"] > mean["NORMAL CAT"] > mean["DEEP CAT"]
    # contour direction differs: ANGRY descends left->right, NORMAL ascends
    assert mapper.pitch_for(0x50, "NORMAL CAT") > mapper.pitch_for(0x51, "NORMAL CAT")
    assert mapper.pitch_for(0x50, "ANGRY CAT") < mapper.pitch_for(0x51, "ANGRY CAT")
    assert set(PERSONALITY_MAPPING) == set(PERSONALITIES)


# 9: special keys use different samples/durations, all derived programmatically
def test_special_key_durations_and_levels(mgr):
    mgr.set_personality("NORMAL CAT")
    cache = mgr._sound_cache["NORMAL CAT"]

    def length(cat):
        b = next(iter(cache[cat]))
        return cache[cat][b][1].get_length()

    def rms(cat):
        b = next(iter(cache[cat]))
        a = np.frombuffer(cache[cat][b][1].get_raw(), dtype=np.int16).astype(np.float32)
        return float(np.sqrt((a ** 2).mean()))

    L = {c: round(length(c), 3) for c in SOUND_CATEGORIES}
    print("durations (s):", L)
    assert L["space"] > L["standard"] > L["nav"] > L["function"] > L["modifier"]
    assert L["escape"] < L["standard"]
    assert rms("modifier") < rms("standard")


def test_variants_stay_recognisable(mgr):
    """Pitch-shifted renditions keep the original's duration and shift spectrum by ~the pitch ratio."""
    cache = mgr._sound_cache["NORMAL CAT"]["standard"]
    buckets = sorted(cache)
    mid = min(buckets, key=lambda b: abs(b - 1.0))

    def stats(snd):
        a = np.frombuffer(snd.get_raw(), dtype=np.int16).reshape(-1, 2)[:, 0].astype(np.float32)
        spec = np.abs(np.fft.rfft(a * np.hanning(len(a))))
        freqs = np.fft.rfftfreq(len(a), 1 / 44100)
        return len(a), float((spec * freqs).sum() / spec.sum())

    n_ref, c_ref = stats(cache[mid][1])
    for b in (buckets[0], buckets[-1]):
        n, c = stats(cache[b][1])
        ratio = c / c_ref
        print(f"bucket {b}: len {n / n_ref:.3f}x, centroid {ratio:.3f}x (target {b / mid:.3f})")
        assert abs(n / n_ref - 1) < 0.01, "duration must be preserved"
        assert abs(ratio - b / mid) < 0.08, "spectral shift must track the pitch ratio"


def test_every_key_pitch_is_within_half_a_bucket_of_a_rendered_variant(mgr, mapper):
    for p in PERSONALITIES:
        cache = mgr._sound_cache[p]
        for vk in mapper.supported_vks():
            prof = mapper.get_key_profile(vk)
            pitch = mapper.pitch_for(vk, p)
            nearest = min(abs(b - pitch) for b in cache[prof.sound_category])
            assert nearest <= 0.0051, (p, prof.name, pitch, nearest)


# NOTE: keep last among mixer-using tests - AudioEngine.shutdown() quits the shared mixer
def test_playback_volume_is_humanised(mgr):
    eng = AudioEngine(sound_manager=mgr, intensity="CHILL", volume=80, enabled=True)
    try:
        import time
        vols = set()
        for _ in range(15):
            eng.trigger_key(0x41)
            time.sleep(0.02)
            vols.update(round(c.get_volume(), 3) for c in eng._channels[:4] if c.get_busy())
        assert len(vols) > 3
    finally:
        eng.shutdown()


# "Do not create hundreds of audio files"
def test_no_audio_file_explosion():
    wavs = list(SOUNDS.rglob("*.wav"))
    assert len(wavs) == 20, f"{len(wavs)} wav files"
