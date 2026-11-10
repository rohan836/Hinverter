"""SPWM gate drive with hardware dead-time, built on the Pico's PIO.

Why PIO and not the hardware PWM slices: RP2040 PWM is edge-aligned and gives
no way to insert non-overlap (dead-time) between the two MOSFETs of an
H-bridge leg, so a "complementary PWM" design briefly shorts the 12 V battery
on every carrier edge. This PIO program switches each leg in the order
high -> dead-time -> low -> dead-time, guaranteeing the two outputs are
never on together.

Cycle budget (SM clock = 125 MHz / 10 = 12.5 MHz, 625 cycles = 50 us = 20 kHz)

    pull noblock      1   (duty_high, or stale OSR if FIFO empty)
    mov x, osr        1
    pull noblock      1   (duty_low,  or stale OSR)
    mov y, osr        1
    set pins, 0b01    1   high gate ON
    hoff: jmp x--     X+1 cycles (both MOSFETs OFF after this)
    set pins, 0b00    1   clamp both OFF
    mov x, 19         1
    d1: jmp x--       20  dead-time (~1.6 us)
    set pins, 0b10    1   low gate ON
    loff: jmp y--     Y+1 cycles
    set pins, 0b00    1   clamp both OFF
    mov x, 19         1
    d2: jmp x--       20  dead-time (~1.6 us) before next high side
    jmp start         1   loop
    --------------------------------
    X + Y = 572 = DUTY_MAX   (572 + 53 = 625 cycles)

NOTE: the program keeps well under the PIO's 32-instruction limit - an
earlier draft used 38 NOP instructions for dead-time and silently exceeded
it. Dead-time is now generated with counter loops (mov + jmp), ~21 cycles
(~1.68 us) each, comfortably above the ~1.5 us requirement.

One state machine runs per leg (A and B). MicroPython pushes the duty pair at
GATE_UPDATE_HZ (5 kHz); because `pull noblock` leaves the OSR untouched when
the FIFO is empty, the PIO reuses the last pushed pair for every carrier
cycle in between — so the 20 kHz carrier runs autonomously and Python never
has to hit the FIFO faster than 5 kHz.

Freewheel words (FREE_HIGH, FREE_LOW) hold both legs with the low-side MOSFETs
conducting, so the transformer primary sees zero differential drive and both
IRF540 anti-parallel diodes can circulate current.
"""

import rp2
from micropython import const
from machine import Pin

import config
from inv_math import clamp, make_sine_lut

_DUTY_MAX = const(572)
_FREE_HIGH = const(0)
_FREE_LOW = const(572)


@rp2.asm_pio(set_init=(rp2.PIO.OUT_LOW, rp2.PIO.OUT_LOW))
def _leg_pwm():
    # Runs once at SM start: make both gate pins outputs.
    set(pindirs, 0b11)
    label("start")
    pull(noblock)          # duty_high -> stale OSR kept if no new word
    mov(x, osr)
    pull(noblock)          # duty_low
    mov(y, osr)
    set(pins, 0b01)        # high ON
    label("hoff")
    jmp(x_dec, "hoff")
    set(pins, 0b00)        # high OFF, both OFF
    mov(x, 19)             # dead-time counter
    label("d1")
    jmp(x_dec, "d1")
    set(pins, 0b10)        # low ON
    label("loff")
    jmp(y_dec, "loff")
    set(pins, 0b00)        # low OFF, both OFF
    mov(x, 19)             # dead-time counter
    label("d2")
    jmp(x_dec, "d2")
    jmp("start")


class SPWMBridge:
    """Drives both H-bridge legs and the fixed sine reference."""

    def __init__(self):
        self._lut = make_sine_lut(config.SINE_LUT_SIZE, _DUTY_MAX // 2)
        self._phase = 0.0
        # duty duty of the modulation ramp (soft-start/soft-stop)
        self._m = 0.0
        self._target_m = 0.0
        self.enabled = False
        self.vout_setting = 230
        self.freq = 50

        a0 = Pin(config.GATE_LEG_A[0], Pin.OUT, value=0)
        a1 = Pin(config.GATE_LEG_A[1], Pin.OUT, value=0)
        b0 = Pin(config.GATE_LEG_B[0], Pin.OUT, value=0)
        b1 = Pin(config.GATE_LEG_B[1], Pin.OUT, value=0)
        self._gate_pins = (a0, a1, b0, b1)

        self._sm_a = rp2.StateMachine(
            config.SPWM_SM_A, _leg_pwm, freq=125_000_000 // 10,
            set_base=Pin(config.GATE_LEG_A[0]))
        self._sm_b = rp2.StateMachine(
            config.SPWM_SM_B, _leg_pwm, freq=125_000_000 // 10,
            set_base=Pin(config.GATE_LEG_B[0]))

    # ---- lifecycle -------------------------------------------------------

    def start(self):
        """Enable the gate outputs and ramp modulation up smoothly."""
        self._sm_a.active(1)
        self._sm_b.active(1)
        self._phase = 0.0
        self._m = 0.0
        self._target_m = 1.0  # scaled by vout setting in tick()
        self.freewheel()
        self.enabled = True

    def stop(self):
        """Ramp modulation to zero, then hold freewheel (differential = 0)."""
        self._target_m = 0.0
        # tick() finishes the stop once the ramp reaches zero.

    def fault_stop(self):
        """Immediate freewheel + latch-off. Gates never go high again
        until SPWMBridge.start() is called deliberately."""
        self.enabled = False
        self._target_m = 0.0
        self._m = 0.0
        self.freewheel()

    def freewheel(self):
        """Push the freewheel duty pair (differential drive = 0)."""
        for sm in (self._sm_a, self._sm_b):
            sm.put(_FREE_HIGH)
            sm.put(_FREE_LOW)

    # ---- modulation ------------------------------------------------------

    def configure(self, vout_setting, freq):
        self.vout_setting = int(vout_setting)
        self.freq = int(freq)

    def _duty_pair(self, fraction):
        """fraction in 0..1 -> (branch-a duty, branch-b duty, complement)."""
        a = int(round(_DUTY_MAX * clamp(fraction, 0.0, 1.0)))
        a = int(clamp(a, 0, _DUTY_MAX))
        b = _DUTY_MAX - a
        return a, b

    def tick(self):
        """Called at GATE_UPDATE_HZ (from a timer IRQ). Keep it tiny."""
        lut = self._lut
        if not self.enabled:
            return
        step = config.SINE_LUT_SIZE * self.freq / config.GATE_UPDATE_HZ
        self._phase = (self._phase + step) % config.SINE_LUT_SIZE

        target = clamp(self.vout_setting / 230.0, 0.3, 1.0)
        if self._target_m == 0.0:          # stopping
            if self._m > 0.02:
                self._m -= 0.02
            else:
                self._m = 0.0
                self.enabled = False
                self.freewheel()
                return
        elif self._m < target:
            self._m = min(target, self._m + 0.02)
        else:
            self._m = max(target, self._m - 0.02)

        s = lut[int(self._phase)] / (_DUTY_MAX // 2)   # -1.0 .. +1.0
        fraction = 0.5 + 0.5 * self._m * s
        a, b = self._duty_pair(fraction)
        # Leg A: high for a, low for b. Leg B: the complement.
        self._sm_a.put(a)
        self._sm_a.put(b)
        self._sm_b.put(b)
        self._sm_b.put(a)

    @property
    def modulation(self):
        return self._m

    def all_low(self):
        """Force every gate pin LOW (used at boot and on hard fault)."""
        self._sm_a.active(0)
        self._sm_b.active(0)
        for p in self._gate_pins:
            p.init(p.OUT, value=0)
