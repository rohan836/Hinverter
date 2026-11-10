"""Minimal SH1106 128x64 I2C OLED driver (MicroPython framebuf).

The SH1106 is a page-addressed controller: 8 pages x 128 columns. Unlike the
SSD1306 there is no 132-column offset handling needed here because we write
all 128 columns per page with the column address window set explicitly.
"""

import time
import framebuf
from micropython import const
from machine import I2C

import config

_PAGES = const(8)
_COLS = const(128)
_ROWS = const(64)

# SH1106 init sequence (page addressing is implicit; column offset = 2)
_INIT_SH1106 = (
    0xAE,        # display off
    0xD5, 0x50,  # clock divide / osc frequency
    0xA8, 0x3F,  # multiplex ratio = 64
    0xD3, 0x00,  # display offset = 0
    0x40,        # start line = 0
    0xAD, 0x8B,  # charge pump (internal DC-DC enable)
    0xA1,        # segment remap (column 127 -> SEG0)
    0xC8,        # COM scan direction remapped
    0xDA, 0x12,  # COM pins config
    0x81, 0x7F,  # contrast
    0xD9, 0x22,  # pre-charge period
    0xDB, 0x35,  # VCOM deselect level
    0xA4,        # display all-on resume (follow RAM)
    0xA6,        # normal (not inverted) display
    0xAF,        # display on
)

# SSD1306 init sequence (page addressing mode, charge pump 0x8D)
_INIT_SSD1306 = (
    0xAE,        # display off
    0xD5, 0x80,  # clock divide / osc frequency
    0xA8, 0x3F,  # multiplex ratio = 64
    0xD3, 0x00,  # display offset = 0
    0x40,        # start line = 0
    0x8D, 0x14,  # charge pump: enable internal DC-DC (REQUIRED - else blank)
    0x20, 0x00,  # memory mode: horizontal... page addressing
    0xA1,        # segment remap
    0xC8,        # COM scan direction remapped
    0xDA, 0x12,  # COM pins config
    0x81, 0xCF,  # contrast
    0xD9, 0xF1,  # pre-charge period
    0xDB, 0x40,  # VCOM deselect level
    0xA4,        # follow RAM content
    0xA6,        # normal display
    0xAF,        # display on
)


class SH1106:
    """Monochrome 128x64 OLED driver.

    Despite the class name (kept for backwards compatibility with existing
    call sites), the panel controller is selectable via the ``driver``
    argument / config.OLED_DRIVER: "SH1106" or "SSD1306". The user's 1.3"
    module identifies itself as SSD1306-compatible (SSD1306 init sequence
    lights every pixel; the SH1106 one leaves it dark).
    """

    def __init__(self, i2c, oled_addr=config.OLED_ADDR, driver=None):
        self._i2c = i2c
        self._addr = oled_addr
        self._driver = (driver or getattr(config, "OLED_DRIVER", "SH1106")).upper()
        if self._driver == "SSD1306":
            self._init_seq = _INIT_SSD1306
            self._col_offset = 0x00
        else:
            self._init_seq = _INIT_SH1106
            self._col_offset = 0x02
        self._buf = bytearray(_COLS * _ROWS // 8)
        self.fb = framebuf.FrameBuffer(self._buf, _COLS, _ROWS,
                                       framebuf.MONO_VLSB)
        self._init_display()

    # ---- low level --------------------------------------------------------

    def _cmd(self, cmd):
        self._i2c.writeto(self._addr, bytes((0x00, cmd)))  # Co=0, D/C#=0

    def _init_display(self):
        for b in self._init_seq:
            self._cmd(b)
        time.sleep_ms(10)
        self.fill(0)
        self.show()

    # ---- drawing ----------------------------------------------------------

    def fill(self, on):
        self.fb.fill(on)

    def text(self, s, x, y, on=1):
        self.fb.text(s, x, y, on)

    def line(self, x0, y0, x1, y1, on=1):
        self.fb.line(x0, y0, x1, y1, on)

    def hline(self, x, y, w, on=1):
        self.fb.hline(x, y, w, on)

    def vline(self, x, y, h, on=1):
        self.fb.vline(x, y, h, on)

    def pixel(self, x, y, on=1):
        self.fb.pixel(x, y, on)

    def rect(self, x, y, w, h, on=1, fill=False):
        self.fb.rect(x, y, w, h, on, fill)

    def rounded_rect(self, x, y, w, h, on=1):
        """1-px rounded-ish outline: plain rect with the 4 corner pixels off."""
        self.rect(x, y, w, h, on)
        self.pixel(x, y, 0)
        self.pixel(x + w - 1, y, 0)
        self.pixel(x, y + h - 1, 0)
        self.pixel(x + w - 1, y + h - 1, 0)

    def text_center(self, s, y, on=1):
        """Center an 8x8-font string horizontally (x guess from len)."""
        w = len(s) * 8
        x = max(2, (_COLS - w) // 2)
        self.fb.text(s, x, y, on)
        return x

    def text_inverse(self, s, x, y, width, on=1):
        """Black text on a solid white bar (our stand-in for color accents)."""
        self.rect(x, y - 1, width, 10, 1, True)
        self.fb.text(s, x + 2, y, 0)

    def icon(self, bitmap, x, y, scale=1, on=1):
        """Draw a 1-bit icon given as a list of strings of '#' and '.'."""
        for row, bits in enumerate(bitmap):
            for col, ch in enumerate(bits):
                if ch != '#':
                    continue
                if scale == 1:
                    self.fb.pixel(x + col, y + row, on)
                else:
                    self.fb.rect(x + col * scale, y + row * scale,
                                 scale, scale, on, True)

    def battery_icon(self, x, y, level_pct, on=1):
        """Small horizontal battery: outline + tip + 0..4 fill bars."""
        w, h = 16, 8
        self.rect(x, y, w, h, on)          # body
        self.vline(x + w, y + 2, h - 4)    # tip
        bars = 0
        pct = max(0, min(100, int(level_pct)))
        if pct > 5:
            bars = (pct * 4 + 99) // 100   # 1..4
        for i in range(bars):
            self.rect(x + 2 + i * 3, y + 2, 2, h - 4, on, True)

    def curve_sin(self, x0, x1, y_mid, amplitude, on=1):
        """Plot one full sine period between x0..x1 centered at y_mid."""
        import math
        prev = None
        for x in range(x0, x1 + 1):
            t = (x - x0) / max(1, x1 - x0) * 2.0 * math.pi
            y = int(y_mid - amplitude * math.sin(t))
            if prev is not None:
                self.line(prev[0], prev[1], x, y, on)
            prev = (x, y)

    def show(self):
        for page in range(_PAGES):
            self._cmd(0xB0 + page)        # page address
            self._cmd(0x00 + self._col_offset)   # low nibble of start column
            self._cmd(0x10)               # high nibble
            chunk = self._buf[page * _COLS:(page + 1) * _COLS]
            self._i2c.writeto(self._addr, b"\x40" + bytes(chunk))

    def clear(self):
        self.fill(0)
        self.show()
