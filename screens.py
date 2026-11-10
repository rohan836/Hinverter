"""OLED screens and encoder-driven UI state machine.

Visual style: "Bruce firmware" adapted to a 128x64 monochrome OLED
  (SSD1306 mode; driver selectable via config.OLED_DRIVER).
  * 1-px rounded-rectangle border on every screen
  * top status bar: firmware id left, battery icon + volts right
  * home pages are Bruce "launcher" style: big pixel icon, < > chevrons,
    inverted white bar for the RUN/STOP state (our stand-in for color)
  * settings is Bruce "Config" style: centered rows, selected row inverted
  * fault screen: full-width inverted bars, blinking acknowledge hint
  * boot splash: logo + sine plot

States
  HOME (INVERTER / BATTERY / THERMAL pages)
  SETTINGS - rotate = select row, short press = edit row, long press = back
  EDIT     - rotate = adjust value, short press = save, long press = cancel
  FAULT    - latched fault; any short press acknowledges (output stays OFF)
"""

import math
from inv_math import clamp, duty_from_volts, batt_pct

_HOME_INVERTER, _HOME_BATTERY, _HOME_THERMAL = 0, 1, 2
_SETTINGS, _EDIT, _FAULT = 3, 4, 5
# Public aliases for main.py
STATE_HOME = _HOME_INVERTER
STATE_FAULT = _FAULT

# (label, settings key, min, max, step, format)
_FIELDS = (
    ("Output V", "vout", 100, 240, 5, "{:.0f}"),
    ("Frequency", "freq", 50, 60, 10, "{:.0f}"),
    ("I Limit A", "icurrent_limit", 0.5, 20.0, 0.5, "{:.1f}"),
    ("OverTemp C", "overtemp_c", 40, 100, 1, "{:.0f}"),
    ("LowBat V", "lowbat_v", 9.0, 12.6, 0.1, "{:.1f}"),
)
_PAGES = (_HOME_INVERTER, _HOME_BATTERY, _HOME_THERMAL)

# 1-bit pixel icons, '#' = lit pixel
_ICON_BOLT = [
    "......#",
    ".....##",
    "....##.",
    "..#####",
    "....###",
    "...##..",
    "..##...",
    ".##....",
    "##.....",
]
_ICON_THERMO = [
    "..##...",
    ".####..",
    ".####..",
    ".####..",
    ".####..",
    "######.",
    "######.",
    ".####..",
    ".####..",
    "..##...",
]
_ICON_SIN = None  # drawn mathematically in splash, not a bitmap


class UI:
    def __init__(self, oled, settings):
        self.oled = oled
        self.settings = settings
        self.state = _HOME_INVERTER
        self.sel = 0
        self.edit_value = 0.0
        self.dirty = True
        self._frame = 0
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

    # ---- boot splash -------------------------------------------------------

    def splash(self):
        o = self.oled
        o.fill(0)
        o.rounded_rect(0, 0, 128, 64)
        o.text_center("HINVERTER", 10)
        o.text_center("SPWM INVERTER", 20)
        o.curve_sin(10, 118, 42, 7)
        o.text_center("12V > 230V", 51)
        o.show()

    # ---- input -------------------------------------------------------------

    def on_event(self, ev):
        if ev is None:
            return None
        kind = ev[0]

        if self.state == _FAULT:
            if kind == "short":
                return ("ack_fault",)
            return None

        if self.state in _PAGES:
            if kind == "rotate":
                self._cycle_page(ev[1])
            elif kind == "short":
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
                self.state = _HOME_INVERTER
            self.dirty = True
            return None

        if self.state == _EDIT:
            _, key, lo, hi, step, fmt = _FIELDS[self.sel]
            if kind == "rotate":
                d = ev[1]
                self.edit_value += step * (1 if d > 0 else -1) * abs(d)
                self.edit_value = min(hi, max(lo, self.edit_value))
            elif kind == "short":
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

    def _cycle_page(self, delta):
        idx = _PAGES.index(self.state)
        if delta >= 0:
            idx = (idx + 1) % len(_PAGES)
        else:
            idx = (idx - 1) % len(_PAGES)
        self.state = _PAGES[idx]

    # ---- rendering ----------------------------------------------------------

    def render(self, force=False):
        self._frame += 1
        if not (self.dirty or force):
            return
        self.dirty = False
        self.oled.fill(0)
        if self.state == _FAULT:
            self._render_fault()
        elif self.state in _PAGES:
            self._render_page_frame()
            if self.state == _HOME_INVERTER:
                self._render_inverter()
            elif self.state == _HOME_BATTERY:
                self._render_battery()
            else:
                self._render_thermal()
        else:
            self._render_settings()
        self.oled.show()

    def _render_page_frame(self):
        """Border + status bar shared by the home pages."""
        o = self.oled
        o.rounded_rect(0, 0, 128, 64)
        o.text("HINV", 4, 3)
        vtxt = "{:.1f}V".format(self.vbat)
        o.text(vtxt, 128 - 4 - 16 - 2 - len(vtxt) * 8, 3)
        o.battery_icon(128 - 4 - 16, 3, batt_pct(self.vbat))
        o.hline(2, 12, 124)

    def _render_inverter(self):
        o = self.oled
        # chevrons
        o.text("<", 4, 30)
        o.text(">", 116, 30)
        # bolt icon
        o.icon(_ICON_BOLT, (128 - 7 * 2) // 2, 15, scale=2)
        # state: inverted bar for RUN, plain for STOP
        if self.state_text == "RUN":
            o.text_inverse("RUN", 52, 42, 26)
        else:
            o.text_center("STOP", 42)
        o.text_center("Out:{}V D:{}%".format(self.vout, self.duty), 53)

    def _render_battery(self):
        o = self.oled
        # big battery body, fill ~ percentage estimate
        pct = batt_pct(self.vbat)
        x, y, w, h = 36, 16, 52, 14
        o.rect(x, y, w, h)
        o.rect(x + w, y + 4, 4, h - 8, 1, True)      # tip
        fill_w = int((w - 4) * pct / 100)
        if fill_w > 0:
            o.rect(x + 2, y + 2, fill_w, h - 4, 1, True)
        o.text_center("{:.1f}V".format(self.vbat), 34)
        o.text_center("{:+.1f}A".format(self.ibat), 46)

    def _render_thermal(self):
        o = self.oled
        o.icon(_ICON_THERMO, (128 - 7 * 2) // 2, 15, scale=2)
        if self.temp is None:
            o.text_center("--.-C", 42)
            filled = 0
        else:
            o.text_center("{:.1f}C".format(self.temp), 42)
            filled = min(96, int(self.temp / 70.0 * 96))
        o.rect(14, 53, 100, 7)
        if filled > 0:
            o.rect(15, 54, filled, 5, 1, True)

    def _render_settings(self):
        o = self.oled
        o.rounded_rect(0, 0, 128, 64)
        o.text("Settings", 4, 3)
        o.hline(2, 13, 124)
        for i, (label, key, lo, hi, step, fmt) in enumerate(_FIELDS):
            y = 15 + i * 9
            if self.state == _EDIT and i == self.sel:
                value = self.edit_value
            else:
                value = float(self.settings.get(key))
            text = "{}:{}".format(label, fmt.format(value))
            if i == self.sel:
                # inverted selected row (Bruce emphasis analog)
                o.rect(2, y - 1, 124, 9, 1, True)
                o.text(text, 4, y, 0)
            else:
                o.text(text, 4, y)

    def _render_fault(self):
        o = self.oled
        blink = (self._frame >> 2) & 1
        o.rounded_rect(0, 0, 128, 64)
        o.rect(2, 2, 124, 12, 1, True)
        o.text("!! FAULT !!", 20, 4, 0)
        o.text_center(str(self.fault_text or "TRIP"), 22)
        o.text_center("Output is OFF", 34)
        hint = "press to ack" + ("_" if blink else " ")
        o.text_center(hint, 48)
