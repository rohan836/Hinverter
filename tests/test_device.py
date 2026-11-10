"""On-device smoke test for Hinverter (runs ON the Pico via: mpremote run tests/test_device.py).

Checks every module end to end without touching the power stage (SPWM is
started/stopped only while gates are unconnected, then all gates forced LOW).
Prints PASS/FAIL per check; exits nonzero on any failure.
"""

import sys

PASS, FAIL = [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print("PASS:", name)
    except Exception as e:
        FAIL.append(name)
        print("FAIL:", name, "->", repr(e))


import machine
from machine import Pin, I2C

import config
import settings as settings_module
from settings import Settings
from sensors import ACS712, BatterySense
import protect
import screens
import spwm
import oled
import encoder
from inv_math import clamp, batt_pct, split_duties, DUTY_MAX


def t_config():
    assert config.GATE_LEG_A == (10, 11)
    assert config.ENC_CLK == 16 and config.ENC_DT == 17 and config.ENC_SW == 18
    assert config.I2C_FREQ == 100_000


def t_settings():
    s = Settings("/test_settings.json")
    s.load()
    assert s.get("vout") == 230 and s.get("freq") == 50
    s.set("vout", 240)
    s.save()
    s2 = Settings("/test_settings.json")
    s2.load()
    assert s2.get("vout") == 240
    import os
    os.remove("/test_settings.json")


def t_batt_pct():
    assert batt_pct(12.75) == 100 and batt_pct(11.5) == 0


def t_i2c_bus():
    i2c = I2C(0, sda=Pin(config.I2C_SDA), scl=Pin(config.I2C_SCL),
              freq=config.I2C_FREQ)
    devs = i2c.scan()
    assert config.OLED_ADDR in devs, "OLED not found on I2C bus (%s)" % devs
    print("     I2C devices:", [hex(a) for a in devs])


def t_oled_draw():
    i2c = I2C(0, sda=Pin(config.I2C_SDA), scl=Pin(config.I2C_SCL),
              freq=config.I2C_FREQ)
    o = oled.SH1106(i2c)          # SSD1306 mode via config
    o.fill(0)
    o.text("DEVICE TEST", 0, 0)
    o.hline(0, 10, 128)
    o.rounded_rect(0, 0, 128, 64)
    o.show()                      # must not raise


def t_mlx90614():
    from sensors import MLX90614
    i2c = I2C(0, sda=Pin(config.I2C_SDA), scl=Pin(config.I2C_SCL),
              freq=config.I2C_FREQ)
    m = MLX90614(i2c)
    t = m.object_temp_c()         # None if absent, exception if broken
    if config.MLX_ADDR not in i2c.scan():
        print("     MLX90614 absent (skipped) - temp reads will show --.-C")
        return
    assert isinstance(t, float), "MLX90614 present but returned %r" % t
    print("     MLX90614 object temp: %.2f C" % t)


def t_bridge():
    b = spwm.SPWMBridge()
    b.start()
    b.stop()
    # stop() ramps modulation to zero over tick() calls, then disables
    for _ in range(60):
        b.tick()
    assert b.enabled is False
    b.all_low()


def t_acs712_zero():
    # inverter is OFF at boot so zero-cal must succeed and be stable
    a = ACS712(config.ADC_OUT_CURRENT)
    z1 = a.zero_calibrate(128)
    assert 0 < z1 < 65536
    amps = abs(a.counts_to_amps(a.raw()))
    assert amps < 1.0, "ACS712 noise floor too high: %.2f A" % amps
    print("     ACS712 zero counts: %d, current reading: %.3f A" % (z1, amps))


def t_encoder_state():
    e = encoder.Encoder()
    ev = e.poll()                   # must not raise
    assert ev is None or ev[0] in ("rotate", "short", "long")


def t_protector():
    p = protect.Protector()
    assert p.check(0.5, 0.5, 25.0, 12.6) is protect.FAULT_NONE
    assert p.check(99.0, 99.0, 25.0, 12.6) == protect.FAULT_OVERCURRENT


def t_screens_render():
    i2c = I2C(0, sda=Pin(config.I2C_SDA), scl=Pin(config.I2C_SCL),
              freq=config.I2C_FREQ)
    o = oled.SH1106(i2c)
    s = Settings("/test_settings.json")
    s.load()
    ui = screens.UI(o, s)
    ui.vbat, ui.ibat, ui.iout, ui.temp = 12.6, 1.2, 3.4, 33.5
    ui.splash()
    for state in (screens._HOME_INVERTER, screens._HOME_BATTERY,
                  screens._HOME_THERMAL, screens._SETTINGS, screens._FAULT):
        ui.state = state
        ui.render(force=True)


for name, fn in sorted(list(globals().items())):
    if name.startswith("t_"):
        check(name[2:], fn)

print()
print("TOTAL: %d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(0 if not FAIL else 1)
