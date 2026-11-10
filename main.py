"""Hinverter — DIY 12V -> 230V SPWM full-bridge inverter firmware.

Boot order matters: sensors are zero-calibrated and the H-bridge stays in
gates forced LOW before anything else is enabled. The output NEVER starts on
its own; the operator must long-press the encoder to run.
"""

import time
from machine import I2C, Pin, Timer, WDT

import config
from inv_math import duty_from_volts
from settings import Settings
from sensors import ACS712, MLX90614, BatterySense
from spwm import SPWMBridge
from protect import Protector
import protect
from oled import SH1106
from screens import UI, STATE_HOME, STATE_FAULT
from encoder import Encoder

I2C_ID = 0


def main():
    settings = Settings()
    settings.load()

    i2c = I2C(I2C_ID, sda=Pin(config.I2C_SDA), scl=Pin(config.I2C_SCL),
              freq=config.I2C_FREQ)
    oled = SH1106(i2c)
    oled.clear()

    # Zero-calibrate BOTH ACS712 modules before anything is enabled.
    out_i = ACS712(config.ADC_OUT_CURRENT)
    bat_i = ACS712(config.ADC_BAT_CURRENT)
    out_i.zero_calibrate()
    bat_i.zero_calibrate()
    mlx = MLX90614(i2c)
    vbat_sense = BatterySense()

    bridge = SPWMBridge()
    bridge.configure(settings.get("vout"), settings.get("freq"))
    prot = Protector()
    prot.apply_limits(settings.get("icurrent_limit"),
                      settings.get("overtemp_c"),
                      settings.get("lowbat_v"))

    enc = Encoder()
    ui = UI(oled, settings)
    ui.vbat = vbat_sense.volts()   # prime the battery readout for the splash
    ui.splash()
    time.sleep_ms(1200)
    led = Pin(config.LED_PIN, Pin.OUT, value=0)

    def _spwm_tick_safe(_t):
        # A timer hard-IRQ that lets an exception escape prints a traceback
        # and wedges the REPL (verified live: Ctrl-C then never reaches the
        # main loop again). Swallow everything - the watchdog is the backstop.
        try:
            bridge.tick()
        except BaseException:
            pass

    spwm_timer = Timer(-1)
    spwm_timer.init(freq=config.GATE_UPDATE_HZ, mode=Timer.PERIODIC,
                    callback=_spwm_tick_safe)

    wdt = WDT(timeout=config.WATCHDOG_MS)

    running = False
    fault_active = False
    last_sensor_ms = 0
    last_display_ms = 0
    i_rms = 0.0
    vbat = 0.0
    ibat = 0.0
    temp = None

    while True:
        wdt.feed()

        # ---- UI events ----
        ev = enc.poll()
        action = ui.on_event(ev)
        if action:
            if action[0] == "toggle_run":
                if running:
                    bridge.stop()
                    running = False
                elif not fault_active:
                    bridge.start()
                    running = True
            elif action[0] == "ack_fault":
                prot.acknowledge()
                fault_active = False
                ui.state_text = "STOP"
                ui.state = STATE_HOME
                ui.dirty = True
            elif action[0] == "settings_changed":
                key = action[1]
                bridge.configure(settings.get("vout"), settings.get("freq"))
                prot.apply_limits(settings.get("icurrent_limit"),
                                  settings.get("overtemp_c"),
                                  settings.get("lowbat_v"))

        # ---- sensor sweep (~10 Hz) ----
        now = time.ticks_ms()
        if time.ticks_diff(now, last_sensor_ms) >= 100:
            last_sensor_ms = now
            if running:
                i_rms = out_i.burst_rms_amps()
                i_peak = out_i.peak_amps()
            else:
                i_rms, i_peak = 0.0, 0.0
            vbat = vbat_sense.volts()
            ibat = bat_i.dc_amps_ema()
            try:
                temp = mlx.object_temp_c()
            except Exception:
                temp = None

            # ---- protection ----
            if running:
                trip = prot.check(i_rms, i_peak, temp, vbat)
                if trip:
                    bridge.fault_stop()
                    running = False
                    fault_active = True
                    ui.fault_text = trip
                    ui.state = STATE_FAULT
                    ui.dirty = True

            # publish telemetry to the UI
            ui.vout = int(settings.get("vout"))
            ui.freq = int(settings.get("freq"))
            ui.duty = int(round(bridge.modulation * 100)) \
                if bridge.modulation else int(round(duty_from_volts(ui.vout) * 100))
            ui.iout = i_rms
            ui.vbat = vbat
            ui.ibat = ibat
            ui.temp = temp
            ui.state_text = "FAULT" if fault_active else ("RUN" if running else "STOP")

        # ---- OLED refresh (4 Hz) ----
        now = time.ticks_ms()
        if time.ticks_diff(now, last_display_ms) >= 250:
            last_display_ms = now
            ui.render(force=True)
        else:
            ui.render()

        led.value(1 if running else 0)
        time.sleep_ms(2)


try:
    main()
except Exception as exc:
    # Last-ditch safety: slam all four gate pins LOW and blink forever.
    try:
        for gp in (config.GATE_LEG_A[0], config.GATE_LEG_A[1],
                   config.GATE_LEG_B[0], config.GATE_LEG_B[1]):
            Pin(gp, Pin.OUT, value=0)
    except Exception:
        pass
    led = Pin(config.LED_PIN, Pin.OUT)
    while True:
        led.toggle()
        time.sleep_ms(150)
