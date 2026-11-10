# Pin map and calibration defaults (see README.md for wiring).
# Everything here is safe to edit; settings.json overrides runtime settings.

I2C_SDA = 4
I2C_SCL = 5
I2C_FREQ = 400_000
OLED_ADDR = 0x3C      # 1.3" 128x64 module (responds to SSD1306 commands)
OLED_DRIVER = "SSD1306"   # "SH1106" or "SSD1306" - this unit is SSD1306-compatible
MLX_ADDR = 0x5A       # MLX90614 IR temperature sensor

ADC_OUT_CURRENT = 0   # GP26 / ADC0 - ACS712 #1, 230 V side output current
ADC_BAT_CURRENT = 1   # GP27 / ADC1 - ACS712 #2, 12 V battery current
ADC_BAT_VOLT = 2      # GP28 / ADC2 - battery voltage via 33k/10k divider

# Encoder wired to GP16/17/18 to match the existing v3.0.0 board wiring
# (GP16-18 are free GPIO; valid for the final build too).
ENC_CLK = 16
ENC_DT = 17
ENC_SW = 18

# Gate drive, consecutive GPIOs required by the PIO 'set' base pin.
GATE_LEG_A = (10, 11)  # Q1 high-left,  Q2 low-left
GATE_LEG_B = (12, 13)  # Q3 high-right, Q4 low-right
LED_PIN = 25

SPWM_SM_A = 0
SPWM_SM_B = 1
CARRIER_HZ = 20_000          # 625 SM cycles @ 12.5 MHz (sys 125 MHz / 10)
GATE_UPDATE_HZ = 5_000       # sine LUT duty refresh rate
SINE_LUT_SIZE = 128
DUTY_MAX = 576               # see spwm.py header for the cycle budget
DEAD_CYCLES = 19             # ~1.52 us dead-time (SM clock 12.5 MHz)
FREE_HIGH = 0                # freewheel word: high MOSFET off ...
FREE_LOW = DUTY_MAX          # ... low MOSFET conducts -> zero differential drive

# ACS712-20A modules powered at 3.3 V (see README): sensitivity =
# 0.1 V/A * (3.3 / 5) = 0.066 V/A. Counts per amp at 3.3 V full scale:
COUNTS_PER_AMP = 0.066 * 65535 / 3.3

# Battery divider 33k (top) / 10k (bottom): Vbat = Vadc * (43/10) = Vadc * 4.3
BATTERY_DIVIDER_GAIN = 4.3

WATCHDOG_MS = 8000
