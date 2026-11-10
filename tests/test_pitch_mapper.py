"""Tests for PitchMapper."""
import pytest
from meowboard.core.pitch_mapper import PitchMapper
from meowboard.config.settings import (
    REGION_FUNCTION,
    REGION_NUMBER,
    REGION_QWERTY,
    REGION_ASDF,
    REGION_ZXCV,
    REGION_SPACE,
    REGION_ENTER,
    REGION_BACKSPACE,
    REGION_ESCAPE,
)


def test_pitch_mapper_initialization():
    mapper = PitchMapper()
    assert mapper is not None


def test_regions_and_subtle_pitch_differences():
    mapper = PitchMapper(pitch_randomness=0.0)

    # Function keys (high)
    pitch_f1, cat_f1, prof_f1 = mapper.get_pitch_for_key(0x70)  # F1
    assert prof_f1.region == REGION_FUNCTION
    assert prof_f1.sound_category == "function"

    # Number row (medium-high)
    pitch_1, cat_1, prof_1 = mapper.get_pitch_for_key(0x31)  # 1
    assert prof_1.region == REGION_NUMBER

    # QWERTY row (medium)
    pitch_q, cat_q, prof_q = mapper.get_pitch_for_key(0x51)  # Q
    assert prof_q.region == REGION_QWERTY

    # ASDF row (medium-low)
    pitch_a, cat_a, prof_a = mapper.get_pitch_for_key(0x41)  # A
    assert prof_a.region == REGION_ASDF

    # ZXCV row (low-medium)
    pitch_z, cat_z, prof_z = mapper.get_pitch_for_key(0x5A)  # Z
    assert prof_z.region == REGION_ZXCV

    # Verify subtle ordering from top to bottom
    assert pitch_f1 >= pitch_1
    assert pitch_1 >= pitch_q
    assert pitch_q >= pitch_a
    assert pitch_a >= pitch_z

    # Pitch differences are SUBTLE (span is less than 0.4 total ratio)
    assert 0.85 <= pitch_z <= 1.0
    assert 1.05 <= pitch_f1 <= 1.25


def test_special_key_mappings():
    mapper = PitchMapper(pitch_randomness=0.0)

    # Spacebar -> longer meow category
    _, cat_space, prof_space = mapper.get_pitch_for_key(0x20)
    assert prof_space.region == REGION_SPACE
    assert cat_space == "space"

    # Enter -> distinct meow
    _, cat_enter, prof_enter = mapper.get_pitch_for_key(0x0D)
    assert prof_enter.region == REGION_ENTER
    assert cat_enter == "enter"

    # Backspace -> inquiring meow
    _, cat_back, prof_back = mapper.get_pitch_for_key(0x08)
    assert prof_back.region == REGION_BACKSPACE
    assert cat_back == "backspace"

    # Escape -> short meow
    _, cat_esc, prof_esc = mapper.get_pitch_for_key(0x1B)
    assert prof_esc.region == REGION_ESCAPE
    assert cat_esc == "escape"


def test_adjacent_keys_have_similar_pitches():
    mapper = PitchMapper(pitch_randomness=0.0)
    pitch_a, _, _ = mapper.get_pitch_for_key(0x41)  # A
    pitch_s, _, _ = mapper.get_pitch_for_key(0x53)  # S
    pitch_d, _, _ = mapper.get_pitch_for_key(0x44)  # D

    assert abs(pitch_a - pitch_s) < 0.03
    assert abs(pitch_s - pitch_d) < 0.03


def test_unmapped_keys_fallback_gracefully():
    mapper = PitchMapper()
    # Arbitrary high virtual key code
    pitch, cat, prof = mapper.get_pitch_for_key(0xE8)
    assert prof.name.startswith("VK_")
    assert cat == "standard"
    assert 0.7 <= pitch <= 1.3
