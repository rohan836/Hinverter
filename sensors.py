"""Sensor drivers: ACS712 current modules, MLX90614 IR temp, battery divider.

Notes
-----
* Both ACS712-20A modules must be powered from **3.3 V**, not 5 V: powered at
  5 V their output swings past the Pico's 3.3 V ADC ceiling above ~8 A.
* ACS712 modules cannot measure DC offset directly at boot time unless the
  load is known-zero. We zero-calibrate at startup (inverter disabled).
* RMS over a short burst (~1 50 Hz cycle) plus an EMA gives a usable
  over-current reading for a DIY build; it is not a precision meter.
"""

import time
from machine import ADC, I2C

import config
from inv_math import clamp, rms, ema


def adc_counts_to_voltage(counts):
    return counts * 3.3 / 65535


class ACS712:
    def __init__(self, adc_id, counts_per_amp=None):
        self._adc = ADC(adc_id)
        self.counts_per_amp = counts_per_amp or config.COUNTS_PER_AMP
        self.zero = 32768          # counts, set by zero_calibrate()
        self._ema = 0.0

    def raw(self):
        return self._adc.read_u16()

    def zero_calibrate(self, samples=256, settle_ms=5):
        """Average the no-load output (inverter MUST be off)."""
        time.sleep_ms(settle_ms)
        total = 0
        for _ in range(samples):
            total += self.raw()
        self.zero = total // samples
        return self.zero

    def counts_to_amps(self, counts):
        return (counts - self.zero) / self.counts_per_amp

    def burst_rms_amps(self, samples=64, sample_us=250):
        """Short burst RMS. Blocks ~ samples*sample_us (~16 ms)."""
        vals = [0.0] * samples
        for i in range(samples):
            vals[i] = self.counts_to_amps(self.raw())
            time.sleep_us(sample_us)
        return rms(vals)

    def peak_amps(self, samples=32, sample_us=150):
        """Largest absolute deviation from zero in a burst (fast fault detect)."""
        peak = 0.0
        for _ in range(samples):
            a = abs(self.counts_to_amps(self.raw()))
            if a > peak:
                peak = a
            time.sleep_us(sample_us)
        return peak

    def dc_amps_ema(self, alpha=0.2):
        """Smoothed DC reading (battery current)."""
        self._ema = ema(self._ema, self.counts_to_amps(self.raw()), alpha)
        return self._ema


class MLX90614:
    """Minimal driver for the TO/BCC-package MLX90614 (SMBus addr 0x5A)."""

    def __init__(self, i2c):
        self._i2c = i2c

    def object_temp_c(self):
        # Register 0x07 = TOBJ1, 16-bit raw, LSB = 0.02 K
        data = self._i2c.readfrom_mem(config.MLX_ADDR, 0x07, 3)
        raw = (data[1] << 8) | data[0]
        if raw == 0xFFFF:
            return None
        return raw * 0.02 - 273.15


class BatterySense:
    """Battery voltage via the 33k/10k divider on ADC2."""

    def __init__(self):
        self._adc = ADC(config.ADC_BAT_VOLT)
        self._ema = 12.0

    def volts(self, alpha=0.25):
        counts = self._adc.read_u16()
        v = adc_counts_to_voltage(counts) * config.BATTERY_DIVIDER_GAIN
        self._ema = ema(self._ema, v, alpha)
        return self._ema
