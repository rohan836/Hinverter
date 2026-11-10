"""PC-side unit checks for the pure logic (run with: python tests/test_logic.py).

These only exercise inv_math and the settings validator - no machine/rp2
imports involved. They are a smoke test, not a hardware simulation.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math

import inv_math
import settings as settings_module


def test_sine_lut():
    lut = inv_math.make_sine_lut(128, 288)
    assert len(lut) == 128
    assert max(lut) <= 288 and min(lut) >= -288
    # quarter-wave symmetry: lut[32] ~= amplitude (sin(pi/2))
    assert abs(lut[32] - 288) <= 1
    assert abs(lut[96] + 288) <= 1
    assert abs(lut[0]) <= 1
    print("sine lut ok")


def test_split_duties():
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        hi, lo = inv_math.split_duties(frac)
        assert hi + lo == inv_math.DUTY_MAX, (hi, lo)
        assert 0 <= hi <= inv_math.DUTY_MAX
    # midpoint must be exactly half of DUTY_MAX (even number)
    hi, lo = inv_math.split_duties(0.5)
    assert hi == lo == inv_math.DUTY_MAX // 2
    # clamping works
    hi, lo = inv_math.split_duties(1.5)
    assert (hi, lo) == (inv_math.DUTY_MAX, 0)
    print("split duties ok")


def test_duty_from_volts():
    assert inv_math.duty_from_volts(230) == 1.0
    assert inv_math.duty_from_volts(115) == 0.5
    assert inv_math.duty_from_volts(0) == 0.3       # clamped
    assert inv_math.duty_from_volts(999) == 1.0     # clamped
    print("duty_from_volts ok")


def test_rms():
    vals = [1.0, -1.0, 1.0, -1.0]
    assert abs(inv_math.rms(vals) - 1.0) < 1e-9
    assert inv_math.rms([]) == 0.0
    sine = [math.sin(x / 10.0) for x in range(200)]
    assert abs(inv_math.rms(sine) - math.sqrt(0.5)) < 0.02
    print("rms ok")


def test_settings_validate():
    d = settings_module._validate({"vout": 999, "freq": 55, "icurrent_limit": 99.0})
    assert d["vout"] == 240          # clamped
    assert d["freq"] == 50           # snap back to valid
    assert d["icurrent_limit"] == 20.0
    d = settings_module._validate({})
    assert d == settings_module._DEFAULTS
    print("settings validation ok")


if __name__ == "__main__":
    test_sine_lut()
    test_split_duties()
    test_duty_from_volts()
    test_rms()
    test_settings_validate()
    print("ALL LOGIC TESTS PASSED")
