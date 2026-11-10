"""HW-040 rotary encoder, tuned for cheap clones with bouncy contacts.

Rotation: full-quadrature state-table decoder. Both CLK and DT are monitored
on every edge; only the four valid Gray-code transitions of a 00 -> 01 -> 11
-> 10 (or the reverse) sequence produce counts, and a full sequence is one
detent. Bounce produces invalid transitions, which are silently discarded, so
tiny knob movements can never generate random +/- steps.

Button: polled with a 30 ms debounce; short press (< LONG_PRESS_MS) -> 'short',
longer hold -> 'long' (fired once when the threshold is crossed).

Wiring: CLK -> GP16, DT -> GP17, SW -> GP18 (3.3 V module logic).
"""

import time
from machine import Pin

import config

LONG_PRESS_MS = 1500
SW_DEBOUNCE_MS = 30

# transition table indexed by (prev << 2) | current: +1 CW, -1 CCW, 0 invalid
_TABLE = [0] * 16
for _p, _c, _d in ((0b00, 0b01, 1), (0b01, 0b11, 1), (0b11, 0b10, 1), (0b10, 0b00, 1),
                   (0b00, 0b10, -1), (0b10, 0b11, -1), (0b11, 0b01, -1), (0b01, 0b00, -1)):
    _TABLE[(_p << 2) | _c] = _d


class Encoder:
    def __init__(self):
        self._clk = Pin(config.ENC_CLK, Pin.IN, Pin.PULL_UP)
        self._dt = Pin(config.ENC_DT, Pin.IN, Pin.PULL_UP)
        self._sw = Pin(config.ENC_SW, Pin.IN, Pin.PULL_UP)

        # ---- rotation state ----
        self._prev = (self._clk.value() << 1) | self._dt.value()
        self._accr = 0
        self._detents = 0

        # ---- button state ----
        self._sw_state = self._sw.value()
        self._sw_last_change = 0
        self._press_start = None
        self._long_fired = False

        self._clk.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,
                      handler=self._edge)
        self._dt.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,
                     handler=self._edge)

    # ---- rotation (hard IRQ: integer math + one list lookup only) ----

    def _edge(self, pin):
        # Hard IRQ must never let an exception escape (it wedges the REPL).
        try:
            new = (self._clk.value() << 1) | self._dt.value()
            delta = _TABLE[(self._prev << 2) | new]
            self._prev = new
            if delta:
                self._accr += delta
                if self._accr >= 4:
                    self._accr -= 4
                    self._detents += 1
                elif self._accr <= -4:
                    self._accr += 4
                    self._detents -= 1
        except BaseException:
            pass

    # ---- main-loop polling ----

    def poll(self):
        """Returns one of ('rotate', steps) | ('short',) | ('long',) | None.

        At most one event per call; call this often (the main loop polls at
        ~500 Hz). Rotation events win over pending button events.
        """
        if self._detents:
            d = self._detents
            self._detents = 0
            if d:
                return ("rotate", d)

        now = time.ticks_ms()
        sw = self._sw.value()
        if sw != self._sw_state:
            if time.ticks_diff(now, self._sw_last_change) > SW_DEBOUNCE_MS:
                self._sw_last_change = now
                if sw == 0:                       # pressed (active-low)
                    self._press_start = now
                    self._long_fired = False
                elif self._press_start is not None:  # released
                    if not self._long_fired:
                        self._press_start = None
                        self._sw_state = sw
                        return ("short",)
                    self._press_start = None
                self._sw_state = sw

        if self._press_start is not None and not self._long_fired:
            if time.ticks_diff(now, self._press_start) >= LONG_PRESS_MS:
                self._long_fired = True
                return ("long",)
        return None
