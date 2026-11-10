"""PC-side smoke test for the Bruce-style UI state machine.

Renders every screen/state through a FakeOled (all primitive calls recorded),
drives the encoder event path through every transition, and asserts no
exceptions and sane call patterns. This is a regression net for typos and
state-machine errors - it cannot check pixels.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from screens import UI, _HOME_INVERTER, _HOME_BATTERY, _HOME_THERMAL, \
                    _SETTINGS, _EDIT, _FAULT
import settings as settings_module


class FakeOled:
    def __init__(self):
        self.calls = []

    def _rec(self, name, *args):
        self.calls.append((name,) + tuple(args))

    def fill(self, on): self._rec("fill", on)
    def text(self, s, x, y, on=1): self._rec("text", s, x, y, on)
    def text_center(self, s, y, on=1): self._rec("text_center", s, y, on)
    def text_inverse(self, s, x, y, w, on=1): self._rec("text_inverse", s, x, y, w, on)
    def line(self, *a): self._rec("line", *a)
    def hline(self, *a): self._rec("hline", *a)
    def vline(self, *a): self._rec("vline", *a)
    def pixel(self, *a): self._rec("pixel", *a)
    def rect(self, *a): self._rec("rect", *a)
    def rounded_rect(self, *a): self._rec("rounded_rect", *a)
    def icon(self, bmp, x, y, scale=1, on=1): self._rec("icon", x, y, scale, on)
    def battery_icon(self, x, y, pct, on=1): self._rec("battery_icon", x, y, pct, on)
    def curve_sin(self, *a): self._rec("curve_sin", *a)
    def show(self): self._rec("show")


def make_ui():
    import tempfile
    # Point the settings store at a throwaway temp file so test saves can
    # never dirty the committed settings.json defaults.
    tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json",
                                      delete=False)
    tmp.close()
    s = settings_module.Settings(path=tmp.name)
    s.load()
    oled = FakeOled()
    ui = UI(oled, s)
    ui.vout = 230
    ui.freq = 50
    ui.duty = 100
    ui.state_text = "STOP"
    ui.iout = 0.0
    ui.vbat = 12.6
    ui.ibat = 1.5
    ui.temp = 33.5
    return ui, oled


def pump(ui, events, render_force=True):
    actions = []
    for ev in events:
        actions.append(ui.on_event(ev))
    ui.render(force=render_force)
    return actions


def test_home_pages_render():
    ui, oled = make_ui()
    ui.splash()
    oled.calls.clear()
    ui.dirty = True
    ui.render(force=True)
    assert ("rounded_rect", 0, 0, 128, 64) in oled.calls
    assert any(c[0] == "text" and c[1] == "HINV" for c in oled.calls)
    assert any(c[0] == "battery_icon" for c in oled.calls)
    assert ("icon", 57, 15, 2, 1) in oled.calls      # bolt, scale 2

    # rotate pages: INVERTER -> BATTERY -> THERMAL -> INVERTER
    pump(ui, [("rotate", 1)])
    assert ui.state == _HOME_BATTERY
    pump(ui, [("rotate", 1)])
    assert ui.state == _HOME_THERMAL
    pump(ui, [("rotate", -1)])
    assert ui.state == _HOME_BATTERY
    pump(ui, [("rotate", -1)])
    assert ui.state == _HOME_INVERTER

    # long press on home returns a RUN toggle request
    (action,) = pump(ui, [("long",)])
    assert action == ("toggle_run",)
    print("home pages ok")


def test_run_bar_inverted():
    ui, oled = make_ui()
    ui.state_text = "RUN"
    ui.render(force=True)
    assert any(c[0] == "text_inverse" and c[1] == "RUN" for c in oled.calls)
    print("run bar ok")


def test_settings_and_edit_flow():
    ui, oled = make_ui()
    pump(ui, [("short",)])                      # home -> settings
    assert ui.state == _SETTINGS
    # selected row is inverted
    ui.render(force=True)
    assert any(c[0] == "rect" and c[3] == 124 and c[6] is True for c in oled.calls)

    pump(ui, [("short",)])                      # edit selected (Output V)
    assert ui.state == _EDIT
    pump(ui, [("rotate", 2)])                   # +10 V
    pump(ui, [("short",)])                      # save
    assert ui.state == _SETTINGS
    assert ui.settings.get("vout") >= 230
    # long press exits settings back to home
    pump(ui, [("long",)])
    assert ui.state == _HOME_INVERTER
    print("settings/edit flow ok")


def test_freq_snaps_to_50_60():
    ui, oled = make_ui()
    pump(ui, [("short",)])        # to settings
    pump(ui, [("rotate", 1)])     # select Frequency
    assert ui.sel == 1
    pump(ui, [("short",)])        # edit
    pump(ui, [("rotate", 3)])     # way past 60 -> clamps to 60
    pump(ui, [("short",)])        # save
    assert ui.settings.get("freq") == 60
    print("freq snap ok")


def test_fault_screen_and_ack():
    ui, oled = make_ui()
    ui.state = _FAULT
    ui.fault_text = "OVERCURRENT"
    ui.render(force=True)
    assert any(c[0] == "rect" and c[3] == 124 and c[6] is True for c in oled.calls)
    (action,) = pump(ui, [("short",)])
    assert action == ("ack_fault",)
    # fault screen ignores rotation
    pump(ui, [("rotate", 1)])
    assert ui.state == _FAULT
    print("fault flow ok")


def test_thermal_bar_fills():
    ui, oled = make_ui()
    pump(ui, [("rotate", 1), ("rotate", 1)])    # to thermal page
    assert ui.state == _HOME_THERMAL
    ui.render(force=True)
    filled = [c for c in oled.calls
              if c[0] == "rect" and c[1] == 15 and c[3] > 0 and c[-1] is True]
    assert filled, "expected partial thermal bar fill"
    print("thermal bar ok")


if __name__ == "__main__":
    test_home_pages_render()
    test_run_bar_inverted()
    test_settings_and_edit_flow()
    test_freq_snaps_to_50_60()
    test_fault_screen_and_ack()
    test_thermal_bar_fills()
    print("ALL UI RENDER TESTS PASSED")
