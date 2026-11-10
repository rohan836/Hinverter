"""HW-040 rotary encoder: rotation via IRQ, button polling for short/long.

Wiring: CLK -> GP14, DT -> GP15, SW -> GP16 (all to Pico GND/3.3V side:
the HW-040 board carries its own pull-ups; SW is active-low).
"""

import time
from machine import Pin

import config

DEBOUNCE_US = 2000
LONG_PRESS_MS = 1500


class Encoder:
    def __init__(self):
        self._clk = Pin(config.ENC_CLK, Pin.IN, Pin.PULL_UP)
        self._dt = Pin(config.ENC_DT, Pin.IN, Pin.PULL_UP)
        self._sw = Pin(config.ENC_SW, Pin.IN, Pin.PULL_UP)
        self._delta = 0
        self._last_irq = 0
        self._press_start = None
        self._long_fired = False
        self._sw.irq(trigger=Pin.IRQ_FALLING, handler=self._sw_down)
        # Rotation IRQ: enabled immediately; debounce inside the handler.
        self._clk.irq(trigger=Pin.IRQ_FALLING, handler=self._clk_changed)

    # ---- rotation (hard IRQ: keep it minimal) ----
    def _clk_changed(self, pin):
        now = time.ticks_us()
        if time.ticks_diff(now, self._last_irq) < DEBOUNCE_US:
            return
        self._last_irq = now
        # DT level at the CLK falling edge tells direction
        self._delta += 1 if self._dt.value() else -1

    # ---- button (IRQ on press start; duration judged in poll()) ----
    def _sw_down(self, pin):
        self._press_start = time.ticks_ms()
        self._long_fired = False

    def poll(self):
        """Call every main-loop iteration. Returns one of
        ('rotate', steps) | ('short',) | ('long',) | None."""
        delta = self._delta
        if delta:
            self._delta = 0
            return ("rotate", delta)

        if self._press_start is not None:
            held_ms = time.ticks_diff(time.ticks_ms(), self._press_start)
            if held_ms >= LONG_PRESS_MS and not self._long_fired:
                self._long_fired = True
                return ("long",)
            if self._sw.value() == 1:  # released
                start, self._press_start = self._press_start, None
                if not self._long_fired:
                    return ("short",)
                self._long_fired = False
                return None
        return None
