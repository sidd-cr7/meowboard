"""
Key-to-pitch mapping for MEOWBOARD.

Every physical key (by Windows virtual-key code) gets a pitch ratio derived from where
it sits on a real keyboard:

    pitch = 1 + (region_base + slope * (x - region_center) - 1) * spread + shift

* region_base  : REGION_PITCH_MAP (number row medium-high, QWERTY medium, ASDF medium-low,
                 ZXCV low-medium, numpad medium-high, function keys high, ...)
* x            : the key's horizontal position in key-widths, so neighbouring keys differ by
                 only `slope` (~0.6 %, about 10 cents) - a gentle left-to-right contour
* spread/shift/slope come from PERSONALITY_MAPPING, so each cat maps the keyboard differently
* result is clamped to [PITCH_MIN, PITCH_MAX] (about -2.2 .. +3.1 semitones) so every sound
  stays recognisably the original recording.

Sound *category* picks the sample/duration treatment:
  standard / space / enter / backspace / escape  - real recordings
  function / modifier / nav                      - the standard recording rendered shorter/softer
"""
from dataclasses import dataclass
import random
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ..config.settings import (
    PERSONALITY_MAPPING,
    PERSONALITY_NORMAL,
    PITCH_BUCKET_STEP,
    PITCH_JITTER,
    PITCH_MAX,
    PITCH_MIN,
    REGION_ASDF,
    REGION_BACKSPACE,
    REGION_DEFAULT,
    REGION_ENTER,
    REGION_ESCAPE,
    REGION_FUNCTION,
    REGION_MODIFIER,
    REGION_NAV,
    REGION_NUMBER,
    REGION_NUMPAD,
    REGION_PITCH_MAP,
    REGION_QWERTY,
    REGION_SPACE,
    REGION_ZXCV,
)

# Horizontal centre (in key widths) of each region; keys left of it go lower (or higher if slope<0)
REGION_CENTER_X: Dict[str, float] = {
    REGION_FUNCTION: 9.0,
    REGION_NUMBER: 6.0,
    REGION_QWERTY: 7.0,
    REGION_ASDF: 6.75,
    REGION_ZXCV: 6.75,
    REGION_NUMPAD: 20.5,
    REGION_MODIFIER: 7.0,
    REGION_NAV: 16.25,
    REGION_DEFAULT: 0.0,
}
NUMPAD_ROW_STEP = -0.007  # each numpad row lower on the pad is a hair lower in pitch

SOUND_CATEGORIES = ("standard", "function", "modifier", "nav", "space", "enter", "backspace", "escape")


@dataclass(frozen=True)
class KeyProfile:
    vk_code: int
    name: str
    region: str
    base_pitch: float      # pitch ratio for the NORMAL CAT mapping (no jitter)
    sound_category: str
    x: float = 0.0         # horizontal position in key widths
    row: int = -1          # 0 = function row ... 5 = space row


def _build_layout() -> List[Tuple[int, str, str, str, int, float]]:
    """(vk, name, region, category, row, x) for every physical key we support."""
    L: List[Tuple[int, str, str, str, int, float]] = []
    add = lambda vk, name, region, cat, row, x: L.append((vk, name, region, cat, row, x))

    # Row 0: Esc + function keys + system keys
    add(0x1B, "ESC", REGION_ESCAPE, "escape", 0, 0.0)
    fx = [2, 3, 4, 5, 6.5, 7.5, 8.5, 9.5, 11, 12, 13, 14]
    for i, x in enumerate(fx):
        add(0x70 + i, f"F{i + 1}", REGION_FUNCTION, "function", 0, x)
    for vk, name, x in [(0x2C, "PRTSC", 15.25), (0x91, "SCRLK", 16.25), (0x13, "PAUSE", 17.25)]:
        add(vk, name, REGION_FUNCTION, "function", 0, x)
    for i in range(12):  # F13-F24
        add(0x7C + i, f"F{13 + i}", REGION_FUNCTION, "function", 0, 18.0 + i * 0.5)

    # Row 1: number row
    num = [(0xC0, "`")] + [(0x30 + d, str(d)) for d in range(1, 10)] + [(0x30, "0"), (0xBD, "-"), (0xBB, "=")]
    for i, (vk, name) in enumerate(num):
        add(vk, name, REGION_NUMBER, "standard", 1, float(i))
    add(0x08, "BACKSPACE", REGION_BACKSPACE, "backspace", 1, 13.5)

    # Row 2: QWERTY
    add(0x09, "TAB", REGION_QWERTY, "standard", 2, 0.5)
    for i, (vk, name) in enumerate([(0x51, "Q"), (0x57, "W"), (0x45, "E"), (0x52, "R"), (0x54, "T"),
                                    (0x59, "Y"), (0x55, "U"), (0x49, "I"), (0x4F, "O"), (0x50, "P"),
                                    (0xDB, "["), (0xDD, "]")]):
        add(vk, name, REGION_QWERTY, "standard", 2, 1.5 + i)
    add(0xDC, "\\", REGION_QWERTY, "standard", 2, 14.0)

    # Row 3: ASDF
    add(0x14, "CAPS", REGION_ASDF, "standard", 3, 0.75)
    for i, (vk, name) in enumerate([(0x41, "A"), (0x53, "S"), (0x44, "D"), (0x46, "F"), (0x47, "G"),
                                    (0x48, "H"), (0x4A, "J"), (0x4B, "K"), (0x4C, "L"),
                                    (0xBA, ";"), (0xDE, "'")]):
        add(vk, name, REGION_ASDF, "standard", 3, 1.75 + i)
    add(0x0D, "ENTER", REGION_ENTER, "enter", 3, 13.5)

    # Row 4: ZXCV
    add(0xE2, "\\(ISO)", REGION_ZXCV, "standard", 4, 1.25)
    for i, (vk, name) in enumerate([(0x5A, "Z"), (0x58, "X"), (0x43, "C"), (0x56, "V"), (0x42, "B"),
                                    (0x4E, "N"), (0x4D, "M"), (0xBC, ","), (0xBE, "."), (0xBF, "/")]):
        add(vk, name, REGION_ZXCV, "standard", 4, 2.25 + i)
    add(0xDF, "OEM8", REGION_QWERTY, "standard", 4, 12.5)

    # Row 5: modifiers + space
    for vk, name, x in [(0xA2, "LCTRL", 0.6), (0x5B, "LWIN", 2.0), (0xA4, "LALT", 3.25),
                        (0xA5, "RALT", 10.75), (0x5C, "RWIN", 12.0), (0x5D, "APPS", 13.25),
                        (0xA3, "RCTRL", 14.5), (0xA0, "LSHIFT", 1.1), (0xA1, "RSHIFT", 13.5)]:
        add(vk, name, REGION_MODIFIER, "modifier", 5 if vk not in (0xA0, 0xA1) else 4, x)
    for vk, name, x in [(0x10, "SHIFT", 1.1), (0x11, "CTRL", 0.6), (0x12, "ALT", 3.25)]:  # generic codes
        add(vk, name, REGION_MODIFIER, "modifier", 5, x)
    add(0x20, "SPACE", REGION_SPACE, "space", 5, 7.0)

    # Navigation cluster
    for vk, name, row, x in [(0x2D, "INS", 1, 15.25), (0x24, "HOME", 1, 16.25), (0x21, "PGUP", 1, 17.25),
                             (0x2E, "DEL", 2, 15.25), (0x23, "END", 2, 16.25), (0x22, "PGDN", 2, 17.25),
                             (0x26, "UP", 4, 16.25),
                             (0x25, "LEFT", 5, 15.25), (0x28, "DOWN", 5, 16.25), (0x27, "RIGHT", 5, 17.25)]:
        add(vk, name, REGION_NAV, "nav", row, x)

    # Numpad
    pad = [
        (1, [(0x90, "NUMLK"), (0x6F, "NUM/"), (0x6A, "NUM*"), (0x6D, "NUM-")], 19.0),
        (2, [(0x67, "NUM7"), (0x68, "NUM8"), (0x69, "NUM9"), (0x6B, "NUM+")], 19.0),
        (3, [(0x64, "NUM4"), (0x65, "NUM5"), (0x66, "NUM6")], 19.0),
        (4, [(0x61, "NUM1"), (0x62, "NUM2"), (0x63, "NUM3")], 19.0),
    ]
    for row, keys, x0 in pad:
        for i, (vk, name) in enumerate(keys):
            add(vk, name, REGION_NUMPAD, "standard", row, x0 + i)
    add(0x60, "NUM0", REGION_NUMPAD, "standard", 5, 19.5)
    add(0x6E, "NUM.", REGION_NUMPAD, "standard", 5, 21.0)
    add(0x6C, "NUMSEP", REGION_NUMPAD, "standard", 5, 22.0)  # VK_SEPARATOR (some layouts)
    add(0x0C, "NUM5(NL off)", REGION_NUMPAD, "standard", 3, 20.0)  # VK_CLEAR

    # Media / browser / launch keys (subtle "function" treatment, near-neutral pitch)
    for i, vk in enumerate(range(0xA6, 0xB8)):
        add(vk, f"MEDIA_{vk:02X}", REGION_DEFAULT, "function", 0, float(i))
    # Misc keys that exist on some keyboards
    for vk, name in [(0x03, "BREAK"), (0x29, "SELECT"), (0x2A, "PRINT"), (0x2B, "EXECUTE"), (0x2F, "HELP"),
                     (0x5F, "SLEEP"), (0xE5, "IME_PROCESS"), (0x15, "KANA"), (0x17, "JUNJA"), (0x18, "FINAL"),
                     (0x19, "KANJI"), (0x1C, "CONVERT"), (0x1D, "NONCONVERT"), (0x1E, "ACCEPT"),
                     (0x1F, "MODECHANGE"), (0xC1, "ABNT1"), (0xC2, "ABNT2"), (0xE1, "OEM_AX"),
                     (0xE3, "ICO_HELP"), (0xE4, "ICO_00"), (0xE6, "ICO_CLEAR"), (0xE9, "OEM_RESET"),
                     (0xEA, "OEM_JUMP"), (0xEB, "OEM_PA1"), (0xEC, "OEM_PA2"), (0xED, "OEM_PA3"),
                     (0xEE, "OEM_WSCTRL"), (0xEF, "OEM_CUSEL"), (0xF0, "OEM_ATTN"), (0xF1, "OEM_FINISH"),
                     (0xF2, "OEM_COPY"), (0xF3, "OEM_AUTO"), (0xF4, "OEM_ENLW"), (0xF5, "OEM_BACKTAB"),
                     (0xFA, "PLAY"), (0xFB, "ZOOM")]:
        add(vk, name, REGION_DEFAULT, "standard", 0, 0.0)
    return L


class PitchMapper:
    """Deterministic per-key pitch with small controlled randomness. Thread-safe (read-only tables)."""

    def __init__(self, pitch_randomness: float = PITCH_JITTER):
        self._pitch_randomness = pitch_randomness
        self._key_map: Dict[int, KeyProfile] = {}
        self._init_mappings()

    # ---- construction

    def _init_mappings(self):
        for vk, name, region, cat, row, x in _build_layout():
            if vk in self._key_map:
                continue
            self._key_map[vk] = KeyProfile(
                vk_code=vk, name=name, region=region, base_pitch=0.0, sound_category=cat, x=x, row=row,
            )
        # fill base_pitch for the NORMAL personality (frozen dataclass -> rebuild)
        for vk, prof in list(self._key_map.items()):
            self._key_map[vk] = KeyProfile(
                vk_code=vk, name=prof.name, region=prof.region,
                base_pitch=self._compute_pitch(prof, PERSONALITY_NORMAL),
                sound_category=prof.sound_category, x=prof.x, row=prof.row,
            )

    @staticmethod
    def _compute_pitch(prof: KeyProfile, personality: str) -> float:
        m = PERSONALITY_MAPPING.get(personality) or PERSONALITY_MAPPING[PERSONALITY_NORMAL]
        base = REGION_PITCH_MAP.get(prof.region, 1.0)
        fixed = prof.region in (REGION_SPACE, REGION_ENTER, REGION_BACKSPACE, REGION_ESCAPE)
        raw = base
        if not fixed:
            raw += m["slope"] * (prof.x - REGION_CENTER_X.get(prof.region, 0.0))
            if prof.region == REGION_NUMPAD:
                raw += NUMPAD_ROW_STEP * (prof.row - 3)
            elif prof.region == REGION_DEFAULT and prof.sound_category == "function":
                raw += 0.004 * (prof.x - 8.0)
        pitch = 1.0 + (raw - 1.0) * m["spread"] + m["shift"]
        return round(max(PITCH_MIN, min(PITCH_MAX, pitch)), 4)

    # ---- queries

    def supported_vks(self) -> List[int]:
        return sorted(self._key_map)

    def get_key_profile(self, vk_code: int) -> KeyProfile:
        """KeyProfile for a VK code; unknown codes get a neutral standard profile (never raises)."""
        prof = self._key_map.get(vk_code)
        if prof is not None:
            return prof
        return KeyProfile(
            vk_code=vk_code, name=f"VK_{vk_code:#04x}", region=REGION_DEFAULT,
            base_pitch=1.0, sound_category="standard",
        )

    def pitch_for(self, vk_code: int, personality: str = PERSONALITY_NORMAL) -> float:
        """Deterministic pitch ratio for this key under this personality's mapping."""
        prof = self.get_key_profile(vk_code)
        if prof.vk_code not in self._key_map:
            return 1.0
        return self._compute_pitch(prof, personality)

    def get_pitch_for_key(self, vk_code: int, personality: str = PERSONALITY_NORMAL
                          ) -> Tuple[float, str, KeyProfile]:
        """(effective_pitch_with_jitter, sound_category, key_profile)."""
        profile = self.get_key_profile(vk_code)
        base = self.pitch_for(vk_code, personality)
        jitter = random.uniform(-self._pitch_randomness, self._pitch_randomness)
        eff = max(PITCH_MIN, min(PITCH_MAX, base + jitter))
        return round(eff, 4), profile.sound_category, profile

    def category_pitches(self, personality: str) -> Dict[str, Set[float]]:
        """For each sound category: the pitch buckets (grid PITCH_BUCKET_STEP) its keys can need,
        including one neighbouring bucket either side to absorb jitter."""
        out: Dict[str, Set[float]] = {c: set() for c in SOUND_CATEGORIES}
        for vk, prof in self._key_map.items():
            p = self._compute_pitch(prof, personality)
            k = round(p / PITCH_BUCKET_STEP)
            for d in (-1, 0, 1):
                b = round(max(PITCH_MIN, min(PITCH_MAX, (k + d) * PITCH_BUCKET_STEP)), 2)
                out[prof.sound_category].add(b)
        return out
