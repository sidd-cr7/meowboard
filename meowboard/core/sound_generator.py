"""
Procedural Cat Meow Acoustic Generator.
Generates naturalistic feline vocalizations with pitch glide, glottal harmonics,
formant vocal tract filtering, and organic amplitude envelopes.
Supports 4 cat personalities (Normal, Kitten, Angry, Deep) and key categories
(standard, space, enter, backspace, escape).
"""
import io
import math
from pathlib import Path
from typing import Dict, Tuple
import wave

import numpy as np

from ..config.settings import (
    DEFAULT_SAMPLE_RATE,
    PERSONALITY_NORMAL,
    PERSONALITY_KITTEN,
    PERSONALITY_ANGRY,
    PERSONALITY_DEEP,
)
from ..utils.logger import logger


def _apply_resonator(signal: np.ndarray, f_res: np.ndarray, bandwidth: float, sr: int) -> np.ndarray:
    """
    Applies a dynamic resonant second-order bandpass filter with time-varying frequency.
    """
    n_samples = len(signal)
    output = np.zeros(n_samples, dtype=np.float32)

    # Precalculate dynamic filter coefficients
    dt = 1.0 / sr
    r = np.exp(-math.pi * bandwidth * dt)
    theta = 2.0 * math.pi * f_res * dt

    # Difference equation: y[n] = 2*r*cos(theta)*y[n-1] - r^2*y[n-2] + (1 - r)*x[n]
    a1 = 2.0 * r * np.cos(theta)
    a2 = - (r * r)
    b0 = 1.0 - r

    y1 = 0.0
    y2 = 0.0
    for i in range(n_samples):
        y0 = b0 * signal[i] + a1[i] * y1 + a2 * y2
        y2 = y1
        y1 = y0
        output[i] = y0

    return output


def generate_meow_pcm(
    personality: str = PERSONALITY_NORMAL,
    category: str = "standard",
    sr: int = DEFAULT_SAMPLE_RATE,
) -> Tuple[np.ndarray, int]:
    """
    Synthesizes a realistic feline meow audio waveform.
    Returns: (float32 numpy array normalized to [-1.0, 1.0], sample_rate)
    """
    # 1. Base parameters based on personality
    if personality == PERSONALITY_KITTEN:
        f_base = 820.0
        f_peak = 1150.0
        f_end = 760.0
        base_dur = 0.28
        formant_scale = 1.35
        vibrato_rate = 7.5
        vibrato_depth = 0.02
        roughness = 0.0
        num_harmonics = 8
    elif personality == PERSONALITY_ANGRY:
        f_base = 340.0
        f_peak = 490.0
        f_end = 310.0
        base_dur = 0.46
        formant_scale = 0.95
        vibrato_rate = 5.0
        vibrato_depth = 0.035
        roughness = 0.35  # Vocal fry / growl
        num_harmonics = 14
    elif personality == PERSONALITY_DEEP:
        f_base = 220.0
        f_peak = 350.0
        f_end = 210.0
        base_dur = 0.48
        formant_scale = 0.78
        vibrato_rate = 4.8
        vibrato_depth = 0.018
        roughness = 0.08
        num_harmonics = 12
    else:  # NORMAL CAT
        f_base = 400.0
        f_peak = 620.0
        f_end = 380.0
        base_dur = 0.38
        formant_scale = 1.0
        vibrato_rate = 6.0
        vibrato_depth = 0.022
        roughness = 0.04
        num_harmonics = 10

    # 2. Adjustments based on category
    if category == "space":
        duration = base_dur * 1.45  # Longer, relaxed meow
        f_peak *= 0.95
    elif category == "enter":
        duration = base_dur * 1.05  # Cheerful upward chirp
        f_peak *= 1.12
        f_end *= 1.08
    elif category == "backspace":
        duration = base_dur * 0.75  # Short questioning meow
        f_peak *= 1.05
        f_end *= 1.15  # Upward questioning pitch bend
    elif category == "escape":
        duration = max(0.12, base_dur * 0.42)  # Staccato chirp
        f_base *= 1.25
        f_peak *= 1.30
        f_end *= 1.20
    else:
        duration = base_dur

    n_samples = max(int(sr * duration), 256)
    t = np.linspace(0.0, duration, n_samples, endpoint=False, dtype=np.float32)
    tau = t / duration  # Normalized progress 0.0 -> 1.0

    # 3. Fundamental frequency contour (Meow pitch curve)
    # Rises during first 35%, then gracefully glides downward
    curve = np.sin(np.pi * (tau ** 0.75)) ** 1.3
    f0 = f_base + (f_peak - f_base) * curve - (f_base - f_end) * (tau ** 1.8)

    # Add natural vibrato
    vibrato = 1.0 + vibrato_depth * np.sin(2.0 * np.pi * vibrato_rate * t)
    f0 = f0 * vibrato

    # 4. Glottal source (Asymmetric pulse train + harmonics)
    phase = 2.0 * np.pi * np.cumsum(f0) / sr
    source = np.zeros(n_samples, dtype=np.float32)

    for h in range(1, num_harmonics + 1):
        # Natural spectral slope (-6 dB/octave)
        amp = 1.0 / (h ** 0.85)
        # Even harmonics slightly subdued, odd harmonics warm
        if h % 2 == 0:
            amp *= 0.75
        source += amp * np.sin(h * phase)

    # Add roughness / growl modulation if applicable
    if roughness > 0.0:
        growl_rate = 55.0  # Hz subharmonic
        growl_mod = 1.0 - roughness * 0.6 * (0.5 + 0.5 * np.sin(2.0 * np.pi * growl_rate * t))
        source *= growl_mod
        # Add slight subharmonic
        source += (roughness * 0.4) * np.sin(0.5 * phase)

    # 5. Formant filtering (Mouth opening /m/ -> /ɛ/ /æ/ -> /o/ /u/)
    # F1 sweeps: 320 Hz -> 850 Hz -> 420 Hz
    f1_contour = (320.0 + 530.0 * np.sin(np.pi * (tau ** 0.8)) ** 1.5) * formant_scale
    # F2 sweeps: 1200 Hz -> 2000 Hz -> 850 Hz
    f2_contour = (1100.0 + 900.0 * np.sin(np.pi * (tau ** 0.7)) ** 1.2 - 300.0 * (tau ** 2)) * formant_scale
    # F3 quasi-stable around 2900 Hz
    f3_contour = (2800.0 + 300.0 * np.sin(np.pi * tau)) * formant_scale

    # Apply resonators
    r1 = _apply_resonator(source, f1_contour, 90.0, sr)
    r2 = _apply_resonator(source, f2_contour, 150.0, sr)
    r3 = _apply_resonator(source, f3_contour, 220.0, sr)

    filtered = 0.50 * r1 + 0.35 * r2 + 0.15 * r3

    # Add subtle nasal murmur during the first 15% (/m/ sound)
    nasal_env = np.clip(1.0 - (tau / 0.18), 0.0, 1.0) ** 2
    nasal_buzz = 0.25 * nasal_env * np.sin(phase)
    audio = filtered + nasal_buzz

    # 6. Amplitude envelope
    # Smooth attack (cosine ramp ~35ms)
    attack_samples = int(sr * min(0.045, duration * 0.15))
    attack_samples = max(attack_samples, 1)
    attack_env = 0.5 * (1.0 - np.cos(np.pi * np.arange(attack_samples) / attack_samples))

    # Smooth decay (~80ms release)
    decay_samples = int(sr * min(0.10, duration * 0.30))
    decay_samples = max(decay_samples, 1)
    decay_env = 0.5 * (1.0 + np.cos(np.pi * np.arange(decay_samples) / decay_samples))

    envelope = np.ones(n_samples, dtype=np.float32)
    envelope[:attack_samples] = attack_env
    envelope[-decay_samples:] = decay_env

    # Body dynamic contour
    body_swell = 0.75 + 0.35 * np.sin(np.pi * (tau ** 0.7))
    envelope = envelope * body_swell

    audio = audio * envelope

    # 7. Normalize with headroom (-3 dB peak ~ 0.707)
    peak = np.max(np.abs(audio))
    if peak > 1e-6:
        audio = (audio / peak) * 0.70

    return audio.astype(np.float32), sr


def save_pcm_to_wav(pcm_mono: np.ndarray, sr: int, output_path: Path):
    """Saves float32 audio array to 16-bit stereo WAV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Convert float32 to int16
    int16_mono = np.clip(pcm_mono * 32767.0, -32768, 32767).astype(np.int16)
    # Duplicate to stereo
    stereo = np.column_stack((int16_mono, int16_mono))

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sr)
        wf.writeframes(stereo.tobytes())


def ensure_sound_assets(assets_dir: Path) -> Dict[str, Dict[str, Path]]:
    """
    Generates and caches default high-quality WAV files for all personalities
    and categories if they do not already exist on disk.
    Returns: {personality: {category: Path}}
    """
    personalities = [PERSONALITY_NORMAL, PERSONALITY_KITTEN, PERSONALITY_ANGRY, PERSONALITY_DEEP]
    categories = ["standard", "space", "enter", "backspace", "escape"]
    sound_files: Dict[str, Dict[str, Path]] = {}

    assets_dir.mkdir(parents=True, exist_ok=True)

    for p in personalities:
        p_slug = p.lower().replace(" ", "_")
        p_dir = assets_dir / p_slug
        p_dir.mkdir(parents=True, exist_ok=True)
        sound_files[p] = {}

        for cat in categories:
            wav_path = p_dir / f"{cat}.wav"
            if not wav_path.exists():
                logger.info("Synthesizing organic cat sound for [%s - %s] -> %s", p, cat, wav_path.name)
                pcm, sr = generate_meow_pcm(personality=p, category=cat)
                save_pcm_to_wav(pcm, sr, wav_path)
            sound_files[p][cat] = wav_path

    return sound_files
