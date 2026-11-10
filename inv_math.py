"""Pure math helpers for the Hinverter firmware.

No hardware imports live in this module, so it can be imported and unit
tested on a PC (see tests/test_logic.py) as well as on the Pico.
"""

import math

DUTY_MAX = 576        # X+Y high-time budget per carrier period (see spwm.py)
DUTY_CENTER = DUTY_MAX // 2


def make_sine_lut(size=128, amplitude=DUTY_CENTER):
    """Signed sine lookup table, peak = ``amplitude`` (int)."""
    return [int(round(math.sin(2.0 * math.pi * i / size) * amplitude))
            for i in range(size)]


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def duty_from_volts(vout):
    """Modulation index (0..1) for a given output-voltage *setting*.

    A 12 V battery and a 12:230 step-up transformer need m ~ 1.0 for a full
    230 V output, so m tracks the setting roughly linearly. The OLED shows
    this as "duty". It is a setting dial, not closed-loop regulation: there
    is no output voltage sensor in the parts list.
    """
    return clamp(float(vout) / 230.0, 0.3, 1.0)


def rms(samples):
    """Root-mean-square of a sequence of instantaneous values."""
    n = len(samples)
    if n == 0:
        return 0.0
    acc = 0.0
    for s in samples:
        acc += s * s
    return math.sqrt(acc / n)


def ema(state, sample, alpha):
    """Exponential moving average step."""
    return state + (sample - state) * clamp(alpha, 0.0, 1.0)


def split_duties(fraction):
    """Split a 0..1 duty fraction for one H-bridge leg.

    Returns (high_cycles, low_cycles) with high + low == DUTY_MAX.
    Used for BOTH legs; leg B simply swaps the pair.
    """
    fraction = clamp(fraction, 0.0, 1.0)
    hi = int(round(DUTY_MAX * fraction))
    hi = int(clamp(hi, 0, DUTY_MAX))
    return hi, DUTY_MAX - hi
