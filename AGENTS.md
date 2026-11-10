# Hinverter — Agent Guidance

DIY 12V→230V SPWM full-bridge inverter firmware for a Raspberry Pi Pico
(RP2040), MicroPython. Driver chain: Pico → PC123 optocouplers → BD139/BD140
totem poles → 4 H-bridge switches (2× paralleled IRF540, 8 total) → 12→230 V
step-up transformer.

**Status:** code exists and is byte-compiled + PC-logic-tested, but NOTHING
HAS BEEN VERIFIED ON HARDWARE. Do not state or imply the inverter is safe,
tested, or mains-ready. Hardware commissioning order is in README.md.

## Build / verify / deploy
- PC checks: `python tests/test_logic.py` (pure logic) and
  `python -m py_compile *.py` (syntax only — machine/rp2/framebuf resolve
  only on-device).
- Flash: copy all root `*.py` + `settings.json` to the Pico root via Thonny or
  `mpremote cp`. `tests/`, README, AGENTS.md do not go on the device.
- On-device SPWM failures (pioasm syntax, wiring) can only be caught on the
  bench with a scope. Iterate on hardware, not by guessing.

## Non-obvious, hard-won facts (do not undo)
- **SPWM runs on PIO, not hardware PWM**: RP2040 PWM is edge-aligned and
  cannot insert dead-time between a leg's two MOSFETs — using it shoots
  through the battery. `spwm.py` budgets 625 SM cycles per 20 kHz carrier with
  ~21-cycle (~1.7 µs) dead-time via counter loops (mov + jmp); X+Y = 570.
  The PIO program is at the 32-instruction limit's edge — an earlier NOP-padded
  draft exceeded it. Keep dead-time ordered high→dead-time→low→dead-time.
- **NEVER put `push` in the SPWM PIO program**: verified on-device that
  `push(noblock)` stalls the SM when the RX FIFO is full, which wedges the TX
  path (duty words never consumed, `sm.put()` blocks forever, bridge hangs).
  The cycle must have no pushes; Python never pulls RX state back.
  keep the program ≤32 instructions. Instantiating `SPWMBridge()` on-device is
  part of the smoke test — never assume module import is enough.
- **Safe state = all gates LOW, SMs halted.** Normal STOP ramps modulation to
  zero (50/50 duties) and then forces gates LOW; faults call
  `SPWMBridge.fault_stop()` immediately. There is no "freewheel push" — the TX
  FIFO is never pre-filled, because a full 4-word FIFO blocks the first
  `tick()` forever and wedged the bridge. Never re-add freewheel pushes.
- **Duty feed is `pull(ifempty, noblock)` + `out(null, 32)` re-arm**: the
  `out` re-opens the ifempty gate each cycle, so the SM pulls a duty pair
  whenever Python has pushed one and otherwise free-runs the stale pair. Plain
  `pull(noblock)` pulls NOTHING on this MicroPython build (verified
  on-device) — do not "simplify" back to it. Python pushes at 5 kHz only.
- **I2C at 100 kHz is shared**: OLED @ 0x3C + MLX90614 @ 0x5A (I2C0,
  GP4/GP5). Never do I2C inside the SPWM timer IRQ — `spwm.tick()` is
  integer/float math + MMIO only.
- **ACS712 at 5 V saturates the 3.3 V ADC** above ~8 A — keep both modules
  powered at 3.3 V (66 mV/A, counts_per_amp in config.py) or add dividers.
- **ACS712 measures current only.** Battery voltage comes from the 33k/10k
  divider on GP28 (gain 4.3). Don't "simplify" by using ACS712 for volts.
- **Gate side may be opto-isolated; ACS712 + divider MUST share GND with the
  Pico ADC** — fully isolating the control domain breaks readings.
- **Output volts on screen = setting × modulation, not a measurement.**
  There is no output voltage sensor in the BOM; duty = live modulation %.
- **Output never auto-starts.** STOP is the boot state; all gates LOW; WDT
  8 s resets to a safe (pins → inputs) state.
- **Settings persist to `settings.json`** with range validation and safe
  fallbacks — keep defaults safe and committed.
- **Encoder long-press is overloaded** by user request (RUN/STOP on home;
  cancel/exit elsewhere); voltage editing lives on the Settings screen, not
  home. Don't "fix" this without asking.
- **The 1.3" panel is SSD1306-compatible, NOT SH1106** (verified on this
  unit: SSD1306 init — 0x8D 0x14 charge pump + 0x20 0x00 page mode — lights
  every pixel; the SH1106 sequence leaves it dark). `config.OLED_DRIVER =
  "SSD1306"`. `oled.py` supports both; column offset depends on driver
  (SSD1306 = 0, SH1106 = 2). Do not "fix" the init back to SH1106.

- **Hard-IRQ handlers must NEVER let an exception escape.** A Ctrl-C that
  landed in the 5 kHz SPWM timer IRQ printed a traceback and wedged the REPL
  permanently (verified live). `_spwm_tick_safe` and `Encoder._edge` wrap all
  IRQs in `try/except BaseException`; keep it that way. If mpremote cannot
  connect, the board was wedged at a boot-crash or IRQ exception — replug USB
  and retry; retrying costs nothing (RELP entry is atomic, file copies do not
  send Ctrl-C again).

## Conventions
- Flat module layout at repo root; files flash directly to the Pico.
- Keep `inv_math.py` free of hardware imports (it is the PC-testable core);
  hardware drivers import `config.py` for pins and constants.
- MicroPython-only APIs: `machine`, `rp2`, `framebuf`, `utime` — no pip
  packages; vendored drivers in-tree only.
- Settings keys are validated in `settings._validate`; add new keys there and
  in `_DEFAULTS`, not ad-hoc.

## When changing gate drive or protection
State the hardware implication explicitly in the commit/README and re-check
README "Wiring & hardware notes" items 1–8 (high-side drive, ACS712 power,
divider gain, pull-up levels). These were all derived from real constraints of
the BOM, not preference.
