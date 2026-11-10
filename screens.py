"""OLED screens and encoder-driven UI state machine.

States
  HOME     - status overview. short press -> SETTINGS, long press -> RUN/STOP
  SETTINGS - rotate = select row, short press = edit row, long press = back
  EDIT     - rotate = adjust value, short press = save, long press = cancel
  FAULT    - fault latch screen; any short press acknowledges (output stays OFF)
"""

import math
from inv_math import duty_from_volts

_HOME, _SETTINGS, _EDIT, _FAULT = 0, 1, 2, 3
# Public aliases for main.py
STATE_HOME, STATE_SETTINGS, STATE_EDIT, STATE_FAULT = _HOME, _SETTINGS, _EDIT, _FAULT

# (label, settings key, min, max, step, format)
_FIELDS = (
    ("Output V", "vout", 100, 240, 5, "{:.0f}"),
    ("Frequency", "freq", 50, 60, 10, "{:.0f}"),
    ("I Limit A", "icurrent_limit", 0.5, 20.0, 0.5, "{:.1f}"),
    ("OverTemp C", "overtemp_c", 40, 100, 1, "{:.0f}"),
    ("LowBat V", "lowbat_v", 9.0, 12.6, 0.1, "{:.1f}"),
)


class UI:
    def __init__(self, oled, settings):
        self.oled = oled
        self.settings = settings
        self.state = _HOME
        self.sel = 0
        self.edit_value = 0.0
        self.dirty = True
        # live telemetry, filled by main()
        self.vout = 230
        self.freq = 50
        self.duty = 100
        self.state_text = "STOP"
        self.iout = 0.0
        self.vbat = 12.0
        self.ibat = 0.0
        self.temp = None
        self.fault_text = None

    # ---- input -----------------------------------------------------------

    def on_event(self, ev):
        if ev is None:
            return None
        kind = ev[0]

        if self.state == _FAULT:
            if kind == "short":
                return ("ack_fault",)
            return None

        if self.state == _HOME:
            if kind == "short":
                self.state = _SETTINGS
            elif kind == "long":
                return ("toggle_run",)
            self.dirty = True
            return None

        if self.state == _SETTINGS:
            if kind == "rotate":
                d = ev[1]
                self.sel = (self.sel + (1 if d > 0 else -1)) % len(_FIELDS)
            elif kind == "short":
                _, key, lo, hi, step, fmt = _FIELDS[self.sel]
                self.edit_value = float(self.settings.get(key))
                self.state = _EDIT
            elif kind == "long":
                self.state = _HOME
            self.dirty = True
            return None

        if self.state == _EDIT:
            _, key, lo, hi, step, fmt = _FIELDS[self.sel]
            if kind == "rotate":
                d = ev[1]
                self.edit_value += step * (1 if d > 0 else -1) * abs(d)
                self.edit_value = min(hi, max(lo, self.edit_value))
            elif kind == "short":
                # frequency snaps to 50/60 only
                val = int(self.edit_value) if key in ("vout", "freq") else self.edit_value
                if key == "freq":
                    val = 50 if val <= 55 else 60
                self.settings.set(key, val)
                self.state = _SETTINGS
                return ("settings_changed", key)
            elif kind == "long":
                self.state = _SETTINGS  # cancel, do not save
            self.dirty = True
            return None
        return None

    # ---- rendering --------------------------------------------------------

    def render(self, force=False):
        if not (self.dirty or force):
            return
        self.dirty = False
        self.oled.fill(0)
        if self.state == _FAULT:
            self._render_fault()
        elif self.state == _HOME:
            self._render_home()
        else:
            self._render_settings()
        self.oled.show()

    def _render_home(self):
        o = self.oled
        o.text("Hinverter    {}Hz".format(self.freq), 0, 0)
        o.hline(0, 9, 128)
        o.text("Out:{}V  D:{}%".format(self.vout, self.duty), 0, 12)
        o.text("State: {}".format(self.state_text), 0, 24)
        o.text("Iout: {:.1f}A".format(self.iout), 0, 36)
        o.text("Bat:{:.1f}V {:+.1f}A".format(self.vbat, self.ibat), 0, 46)
        if self.temp is None:
            t = "Sink: --.-C"
        else:
            t = "Sink: {:.1f}C".format(self.temp)
        o.text(t, 0, 56)

    def _render_settings(self):
        o = self.oled
        o.text("Settings  (hold: back)", 0, 0)
        o.hline(0, 9, 128)
        for i, (label, key, lo, hi, step, fmt) in enumerate(_FIELDS):
            y = 12 + i * 11
            prefix = ">" if i == self.sel else " "
            if self.state == _EDIT and i == self.sel:
                value = self.edit_value
            else:
                value = float(self.settings.get(key))
            o.text("{}{}:{}".format(prefix, label, fmt.format(value)), 0, y)
        if self.state == _EDIT:
            o.text("press=save  hold=skip", 0, 56)

    def _render_fault(self):
        o = self.oled
        o.hline(0, 20, 128)
        o.hline(0, 44, 128)
        o.text("!! FAULT !!", 34, 8)
        o.text(str(self.fault_text or "TRIP"), 0, 26)
        o.text("Output is OFF", 0, 52)
        o.text("press to acknowledge", 0, 62 - 8)
