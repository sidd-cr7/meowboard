"""
Application Configuration and Constants for MEOWBOARD.
"""
from dataclasses import dataclass, asdict
from typing import Dict, List
import json
import os
from pathlib import Path


# Intensity channel limits (Requirement 4)
INTENSITY_CHANNELS: Dict[str, int] = {
    "CHILL": 4,
    "NORMAL": 12,
    "CHAOS": 24,
}

# Supported cat personalities (Requirement 5)
PERSONALITY_NORMAL = "NORMAL CAT"
PERSONALITY_KITTEN = "KITTEN"
PERSONALITY_ANGRY = "ANGRY CAT"
PERSONALITY_DEEP = "DEEP CAT"

PERSONALITIES: List[str] = [
    PERSONALITY_NORMAL,
    PERSONALITY_KITTEN,
    PERSONALITY_ANGRY,
    PERSONALITY_DEEP,
]

# Audio settings
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_AUDIO_CHANNELS = 2  # Stereo
DEFAULT_AUDIO_BUFFER = 512   # Low latency (~11.6ms)

# Keyboard Pitch Regions (Requirement 3)
REGION_FUNCTION = "FUNCTION"
REGION_NUMBER = "NUMBER"
REGION_QWERTY = "QWERTY"
REGION_ASDF = "ASDF"
REGION_ZXCV = "ZXCV"
REGION_NUMPAD = "NUMPAD"
REGION_SPACE = "SPACE"
REGION_ENTER = "ENTER"
REGION_BACKSPACE = "BACKSPACE"
REGION_ESCAPE = "ESCAPE"
REGION_MODIFIER = "MODIFIER"
REGION_DEFAULT = "DEFAULT"
REGION_NAV = "NAV"

# Base pitch factor ranges relative to 1.0 (subtle differences)
# Adjacent keys have close pitches, subtle tonal variation
REGION_PITCH_MAP: Dict[str, float] = {
    REGION_FUNCTION: 1.14,    # High, subtle chirp
    REGION_NUMBER: 1.08,      # Medium to slightly high
    REGION_QWERTY: 1.03,      # Medium
    REGION_ASDF: 0.98,        # Medium to slightly low
    REGION_ZXCV: 0.92,        # Low to medium
    REGION_NUMPAD: 1.06,      # Medium to slightly high
    REGION_SPACE: 0.94,       # Longer, warm meow
    REGION_ENTER: 1.05,       # Distinct upbeat meow
    REGION_BACKSPACE: 1.10,   # Inquiring meow
    REGION_ESCAPE: 1.18,      # Short staccato squeak
    REGION_MODIFIER: 0.96,    # Subtle soft tone
    REGION_NAV: 1.04,         # Navigation cluster: gentle, slightly shorter
    REGION_DEFAULT: 1.00,
}

# Hard limits for any pitch ratio (about -2.2 / +3.1 semitones): keeps every variant
# recognisably the original recording. Pitch buckets are pre-rendered on this grid.
PITCH_MIN = 0.88
PITCH_MAX = 1.20
PITCH_BUCKET_STEP = 0.01
PITCH_JITTER = 0.004   # +/- random ratio jitter per press (about 7 cents)

# Per-personality key->pitch mapping.
#   shift:  moves the whole keyboard up/down (added to the ratio)
#   spread: scales how far each region sits from 1.0 (row-to-row contrast)
#   slope:  pitch change per key-width, left->right (negative = descending to the right)
PERSONALITY_MAPPING: Dict[str, Dict[str, float]] = {
    "NORMAL CAT": {"shift": 0.000, "spread": 1.00, "slope": 0.0060},
    "KITTEN":     {"shift": 0.020, "spread": 0.75, "slope": 0.0045},
    "ANGRY CAT":  {"shift": -0.020, "spread": 1.15, "slope": -0.0060},
    "DEEP CAT":   {"shift": -0.015, "spread": 0.85, "slope": 0.0035},
}


@dataclass
class AppConfig:
    """User-configurable settings persisted locally."""
    enabled: bool = True
    volume: int = 75  # 0 to 100
    intensity: str = "NORMAL"  # CHILL, NORMAL, CHAOS
    personality: str = PERSONALITY_NORMAL
    start_with_windows: bool = False
    minimize_to_tray_on_close: bool = True
    audio_buffer_size: int = DEFAULT_AUDIO_BUFFER

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        # Validation
        if filtered.get("intensity") not in INTENSITY_CHANNELS:
            filtered["intensity"] = "NORMAL"
        if filtered.get("personality") not in PERSONALITIES:
            filtered["personality"] = PERSONALITY_NORMAL
        if "volume" in filtered:
            filtered["volume"] = max(0, min(100, int(filtered["volume"])))
        return cls(**filtered)
