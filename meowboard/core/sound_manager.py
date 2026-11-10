"""
Preloaded In-Memory Sound Manager.

* Loads every real cat-meow WAV (4 personalities x 5 categories) into memory once.
* Normalizes loudness (RMS target with peak ceiling) so no personality/key is much louder.
* Pre-renders subtle pitch variants with a duration-preserving pitch shift
  (resample + WSOLA time-stretch) so pitch changes do not change playback speed.
* Missing/corrupt assets degrade gracefully (fallback chain, never an exception on keypress).
* Lookup on keypress is O(1) dictionary access: no disk, decoding or DSP.
"""
from pathlib import Path
import random
import threading
from typing import Dict, List, Optional, Tuple
import wave

import numpy as np

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    pygame = None
    PYGAME_AVAILABLE = False

from ..config.settings import (
    DEFAULT_SAMPLE_RATE,
    PERSONALITIES,
    PERSONALITY_NORMAL,
    PITCH_MAX,
    PITCH_MIN,
)
from ..utils.logger import logger
from .pitch_mapper import KeyProfile, PitchMapper

CATEGORIES = ("standard", "space", "enter", "backspace", "escape")

# Loudness normalization (int16 scale)
TARGET_RMS = 5000.0
PEAK_CEILING = 0.89 * 32767.0

# Variants rendered around each pitch bucket (bucket grid = PITCH_BUCKET_STEP) so that repeated
# presses of the same key pick different, but all very close, renditions.
MICRO_OFFSETS = (-0.004, 0.0, 0.004)

# How each sound category is derived: (source recording, duration factor, gain).
# Real recordings for standard/space/enter/backspace/escape; the rest are rendered
# programmatically from the standard recording (shorter / softer) - no extra audio files.
CATEGORY_SPECS = {
    "standard":  ("standard", 1.00, 1.00),
    "function":  ("standard", 0.65, 0.90),   # short chirp
    "modifier":  ("standard", 0.45, 0.60),   # soft, brief
    "nav":       ("standard", 0.80, 0.85),
    "space":     ("space", 1.00, 1.00),
    "enter":     ("enter", 1.00, 1.00),
    "backspace": ("backspace", 1.00, 1.00),
    "escape":    ("escape", 1.00, 1.00),
}


def slug(personality: str) -> str:
    return personality.lower().replace(" ", "_")


# --------------------------------------------------------------------------- DSP

def _resample_audio(audio: np.ndarray, pitch_ratio: float) -> np.ndarray:
    """Linear-interpolation resample. ratio>1 -> higher pitch AND shorter (speed change)."""
    if abs(pitch_ratio - 1.0) < 1e-4:
        return audio.copy()
    n_orig = len(audio)
    n_new = max(int(round(n_orig / pitch_ratio)), 16)
    idx = np.linspace(0.0, n_orig - 1, n_new, endpoint=True)
    base = np.arange(n_orig)
    if audio.ndim == 1:
        out = np.interp(idx, base, audio)
    else:
        out = np.column_stack([np.interp(idx, base, audio[:, c]) for c in range(audio.shape[1])])
    return out.astype(audio.dtype)


def _time_stretch_wsola(audio: np.ndarray, target_len: int, frame: int = 1024, tol: int = 256) -> np.ndarray:
    """
    Waveform-similarity overlap-add: changes duration to target_len without changing pitch.
    audio: float32 (n, ch). Returns float32 (target_len, ch).
    """
    n_in, n_ch = audio.shape
    if target_len == n_in or n_in < frame * 2:
        # Too short for WSOLA: simple crop/pad
        out = np.zeros((target_len, n_ch), dtype=np.float32)
        m = min(target_len, n_in)
        out[:m] = audio[:m]
        return out

    hs = frame // 2
    window = np.hanning(frame).astype(np.float32)[:, None]
    ratio = n_in / target_len
    ha = hs * ratio

    n_frames = int(np.ceil((target_len - frame) / hs)) + 1
    out = np.zeros((n_frames * hs + frame, n_ch), dtype=np.float32)
    norm = np.zeros(out.shape[0], dtype=np.float32)
    mono = audio.mean(axis=1)

    prev_pos = 0
    for k in range(n_frames):
        nominal = int(round(k * ha))
        if k == 0:
            pos = 0
        else:
            nat = prev_pos + hs  # where the previous frame would naturally continue
            template = mono[nat:nat + frame]
            lo = max(0, nominal - tol)
            hi = min(n_in - frame, nominal + tol)
            if len(template) < frame or hi <= lo:
                pos = min(max(nominal, 0), n_in - frame)
            else:
                seg = mono[lo:hi + frame]
                corr = np.correlate(seg[::2], template[::2], mode="valid")
                pos = lo + int(np.argmax(corr)) * 2
                pos = min(pos, n_in - frame)
        o = k * hs
        out[o:o + frame] += audio[pos:pos + frame] * window
        norm[o:o + frame] += window[:, 0]
        prev_pos = pos

    norm = np.maximum(norm, 1e-3)
    out = out / norm[:, None]
    out = out[:target_len]
    if len(out) < target_len:
        out = np.vstack([out, np.zeros((target_len - len(out), n_ch), dtype=np.float32)])
    return out


def pitch_shift(audio: np.ndarray, ratio: float) -> np.ndarray:
    """
    Duration-preserving pitch shift of int16 (n, ch) audio by `ratio` (1.0 = unchanged).
    Output length equals input length (+/- 1 sample) so playback speed is unchanged.
    """
    if abs(ratio - 1.0) < 1e-3:
        return audio.copy()
    n_orig = len(audio)
    shifted = _resample_audio(audio.astype(np.float32), ratio)
    stretched = _time_stretch_wsola(shifted, n_orig)
    # Keep the natural fade-out intact (WSOLA tail can be slightly uneven)
    fade = min(int(0.01 * DEFAULT_SAMPLE_RATE), n_orig // 4)
    if fade > 0:
        stretched[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)[:, None]
    return np.clip(stretched, -32768, 32767).astype(np.int16)


def normalize_loudness(pcm: np.ndarray, target_rms: float = TARGET_RMS,
                       peak_ceiling: float = PEAK_CEILING) -> np.ndarray:
    """RMS-normalize int16 audio toward target_rms without exceeding peak_ceiling (no clipping)."""
    x = pcm.astype(np.float32)
    rms = float(np.sqrt(np.mean(x * x)))
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if rms < 1.0 or peak < 1.0:
        return pcm
    gain = min(target_rms / rms, peak_ceiling / peak)
    return np.clip(x * gain, -32768, 32767).astype(np.int16)


def _load_wav_as_pcm(wav_path: Path, target_sr: int = DEFAULT_SAMPLE_RATE) -> Tuple[np.ndarray, int]:
    """Reads a WAV into stereo int16 at target_sr. Raises on unreadable/unsupported files."""
    with wave.open(str(wav_path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sampwidth == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
    elif sampwidth == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
    elif sampwidth == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 65536.0
    else:
        raise ValueError(f"unsupported sample width {sampwidth}")

    if n_channels > 1:
        audio = audio[: len(audio) // n_channels * n_channels].reshape(-1, n_channels)[:, :2]
        if audio.shape[1] == 1:
            audio = np.column_stack((audio[:, 0], audio[:, 0]))
    else:
        audio = np.column_stack((audio, audio))

    if len(audio) < 64:
        raise ValueError("audio too short")

    if framerate != target_sr:
        n_new = int(len(audio) * target_sr / framerate)
        idx = np.linspace(0.0, len(audio) - 1, n_new)
        base = np.arange(len(audio))
        audio = np.column_stack([np.interp(idx, base, audio[:, c]) for c in range(2)])

    return np.clip(audio, -32768, 32767).astype(np.int16), target_sr


# --------------------------------------------------------------------------- manager

class SoundManager:
    """Preloads, normalizes and pitch-prerenders all samples."""

    def __init__(self, assets_dir: Optional[Path] = None, pitch_mapper: Optional[PitchMapper] = None,
                 background_preload: bool = False):
        import sys
        if assets_dir:
            self._assets_dir = Path(assets_dir)
        elif getattr(sys, "frozen", False):
            base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
            p = base / "meowboard" / "assets" / "sounds"
            if not p.exists():
                p = Path(sys.executable).parent / "_internal" / "meowboard" / "assets" / "sounds"
            self._assets_dir = p
        else:
            self._assets_dir = Path(__file__).resolve().parent.parent / "assets" / "sounds"

        self._pitch_mapper = pitch_mapper or PitchMapper()
        self._current_personality = PERSONALITY_NORMAL
        self._lock = threading.RLock()
        self._last_variant: Dict[Tuple[str, str, float], int] = {}

        # {personality: {category: (pcm_int16_stereo, sr)}}
        self._raw_samples: Dict[str, Dict[str, Tuple[np.ndarray, int]]] = {}
        # {personality: {category: {pitch_bucket: [Sound | ndarray, ...]}}}
        self._sound_cache: Dict[str, Dict[str, Dict[float, List]]] = {}
        # Files that could not be loaded, for diagnostics: {(personality, category): reason}
        self.missing_assets: Dict[Tuple[str, str], str] = {}

        self._init_audio_assets()
        self.preload_personality(self._current_personality)

        if background_preload:
            threading.Thread(target=self._preload_remaining, name="MeowPreload", daemon=True).start()

    # ---- loading

    def _init_audio_assets(self):
        """Loads every available WAV, then fills gaps with a fallback chain."""
        for personality in PERSONALITIES:
            self._raw_samples[personality] = {}
            for cat in CATEGORIES:
                path = self._assets_dir / slug(personality) / f"{cat}.wav"
                try:
                    pcm, sr = _load_wav_as_pcm(path)
                    self._raw_samples[personality][cat] = (normalize_loudness(pcm), sr)
                except FileNotFoundError:
                    self.missing_assets[(personality, cat)] = "file not found"
                except Exception as e:
                    self.missing_assets[(personality, cat)] = str(e)
                    logger.error("Failed loading WAV %s: %s", path, e)

        if self.missing_assets:
            logger.warning("%d audio asset(s) missing/unreadable; applying fallbacks", len(self.missing_assets))
            self._apply_fallbacks()

    def _apply_fallbacks(self):
        """Fill gaps: same-personality standard -> any other loaded sample -> synthesized."""
        for (personality, cat) in list(self.missing_assets):
            sample = self._raw_samples[personality].get("standard")
            if sample is None:
                for p in PERSONALITIES:
                    sample = self._raw_samples[p].get(cat) or self._raw_samples[p].get("standard")
                    if sample is not None:
                        break
            if sample is None:
                sample = self._synthesize(personality, cat)
            if sample is not None:
                self._raw_samples[personality][cat] = sample

    @staticmethod
    def _synthesize(personality: str, cat: str) -> Optional[Tuple[np.ndarray, int]]:
        try:
            from .sound_generator import generate_meow_pcm
            mono, sr = generate_meow_pcm(personality=personality, category=cat)
            i16 = np.clip(mono * 32767.0, -32768, 32767).astype(np.int16)
            return normalize_loudness(np.column_stack((i16, i16))), sr
        except Exception as e:
            logger.error("Synthesis fallback failed for %s/%s: %s", personality, cat, e)
            return None

    @staticmethod
    def _shape_category(pcm: np.ndarray, duration: float, gain: float) -> np.ndarray:
        """Shortens (with a smooth fade-out) and/or scales a recording to derive a category."""
        out = pcm
        if duration < 0.999:
            n = max(int(len(pcm) * duration), 512)
            out = pcm[:n].astype(np.float32)
            fade = min(int(0.06 * DEFAULT_SAMPLE_RATE), n // 2)
            out[-fade:] *= (0.5 * (1.0 + np.cos(np.linspace(0, np.pi, fade, dtype=np.float32))))[:, None]
        if gain != 1.0:
            out = out.astype(np.float32) * gain
        return np.clip(out, -32768, 32767).astype(np.int16)

    def preload_personality(self, personality: str):
        """Pre-renders every needed (category, pitch bucket) variant for one personality
        (idempotent, thread-safe). Only buckets that some key actually maps to are rendered."""
        with self._lock:
            if personality in self._sound_cache:
                return
            raw = self._raw_samples.get(personality)
            if not raw:
                logger.warning("No audio available for %s", personality)
                return
            logger.info("Pre-rendering sound variations for: %s", personality)
            needed = self._pitch_mapper.category_pitches(personality)
            cache: Dict[str, Dict[float, List]] = {}

            for cat, (src_cat, dur, gain) in CATEGORY_SPECS.items():
                src = raw.get(src_cat) or raw.get("standard")
                if src is None:
                    continue
                buckets = needed.get(cat) or {1.0}
                base = self._shape_category(src[0], dur, gain)
                cache[cat] = {}
                for b in sorted(buckets):
                    variants = []
                    for off in MICRO_OFFSETS:
                        ratio = max(PITCH_MIN, min(PITCH_MAX, b + off))
                        try:
                            shifted = pitch_shift(base, ratio)
                        except Exception as e:
                            logger.warning("Pitch shift failed (%s/%s %.3f): %s", personality, cat, ratio, e)
                            shifted = base.copy()
                        variants.append(self._to_sound(shifted))
                    cache[cat][round(b, 2)] = variants
            self._sound_cache[personality] = cache

    def _preload_remaining(self):
        for p in PERSONALITIES:
            try:
                self.preload_personality(p)
            except Exception as e:
                logger.error("Background preload of %s failed: %s", p, e)

    @staticmethod
    def _to_sound(pcm: np.ndarray):
        if PYGAME_AVAILABLE and pygame.mixer.get_init():
            try:
                return pygame.mixer.Sound(buffer=np.ascontiguousarray(pcm).tobytes())
            except Exception as e:
                logger.debug("Sound creation deferred: %s", e)
        return pcm

    def finalize_sounds(self):
        """Converts any stored PCM arrays to mixer Sounds (call after the mixer is initialized)."""
        with self._lock:
            for cats in self._sound_cache.values():
                for buckets in cats.values():
                    for variants in buckets.values():
                        for i, v in enumerate(variants):
                            if isinstance(v, np.ndarray):
                                variants[i] = self._to_sound(v)

    def reset_sounds(self):
        """Rebuilds mixer Sounds after an audio-device re-init (old Sound objects become invalid)."""
        with self._lock:
            self._sound_cache.clear()
            self.preload_personality(self._current_personality)

    # ---- API

    @property
    def current_personality(self) -> str:
        return self._current_personality

    def set_personality(self, personality: str):
        if personality not in PERSONALITIES:
            personality = PERSONALITY_NORMAL
        if personality not in self._sound_cache:
            self.preload_personality(personality)
        self._current_personality = personality

    def get_sound(self, personality: str, category: str, pitch: float) -> Optional[object]:
        """Nearest pre-rendered variant for explicit (personality, category, pitch)."""
        cats = self._sound_cache.get(personality)
        if cats is None:
            self.preload_personality(personality)
            cats = self._sound_cache.get(personality)
        if not cats:
            return None
        buckets = cats.get(category) or cats.get("standard") or next(iter(cats.values()), None)
        if not buckets:
            return None
        key = min(buckets, key=lambda k: abs(k - pitch))
        variants = buckets[key]
        if not variants:
            return None
        # Anti-repeat: never pick the same rendition twice in a row for this slot
        slot = (personality, category, key)
        last = self._last_variant.get(slot, -1)
        choices = [i for i in range(len(variants)) if i != last] or [0]
        idx = random.choice(choices)
        self._last_variant[slot] = idx
        sound = variants[idx]
        if isinstance(sound, np.ndarray) and PYGAME_AVAILABLE and pygame.mixer.get_init():
            sound2 = self._to_sound(sound)
            if not isinstance(sound2, np.ndarray):
                for i, v in enumerate(variants):
                    if v is sound:
                        variants[i] = sound2
                sound = sound2
        return sound

    def get_sound_for_key(self, vk_code: int) -> Tuple[Optional[object], KeyProfile]:
        """O(1) retrieval for a key. Never raises; returns (None, profile) if nothing is available."""
        effective_pitch, category, profile = self._pitch_mapper.get_pitch_for_key(
            vk_code, self._current_personality)
        try:
            return self.get_sound(self._current_personality, category, effective_pitch), profile
        except Exception as e:
            logger.debug("get_sound_for_key error: %s", e)
            return None, profile
