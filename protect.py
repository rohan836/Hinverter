"""Protection: over-current, over-temperature, low-battery.

All faults LATCH: the inverter output is forced off (all gates LOW) and stays off
until the operator acknowledges with a short encoder press. There is no
auto-retry, by design.
"""

import config

FAULT_NONE = None
FAULT_OVERCURRENT = "OVERCURRENT"
FAULT_OVERTEMP = "OVERTEMP"
FAULT_LOWBAT = "LOW BATTERY"

class Protector:
    def __init__(self, oled_write=None):
        # limits in amps / degC / volts; main() overrides from settings
        self.limit_i = 8.0
        self.limit_t = 70.0
        self.limit_v = 10.8
        self.fault = FAULT_NONE
        self._i_fast = 0.0    # EMA of recent burst peaks
        self._i_slow = 0.0    # EMA of burst RMS (thermal trip)
        self._confirm = 0     # consecutive over-limit readings required

    def apply_limits(self, icurrent_limit, overtemp_c, lowbat_v):
        self.limit_i = float(icurrent_limit)
        self.limit_t = float(overtemp_c)
        self.limit_v = float(lowbat_v)

    def check(self, i_rms, i_peak, temp_c, vbat):
        """Feed a measurement round; returns fault string or None."""
        if self.fault is not None:
            return self.fault

        self._i_fast = i_peak          # instantaneous-ish
        self._i_slow += (i_rms - self._i_slow) * 0.3

        # fast: any burst peak above 1.5x limit trips immediately
        if self._i_fast > self.limit_i * 1.5:
            self._trip(FAULT_OVERCURRENT)
            return self.fault
        # slow: RMS above limit trips after 5 measurement rounds
        if self._i_slow > self.limit_i:
            self._confirm += 1
            if self._confirm >= 5:
                self._trip(FAULT_OVERCURRENT)
                return self.fault
        else:
            self._confirm = 0

        if temp_c is not None and temp_c > self.limit_t:
            self._trip(FAULT_OVERTEMP)
            return self.fault

        if vbat < self.limit_v:
            self._trip(FAULT_LOWBAT)
            return self.fault

        return FAULT_NONE

    def _trip(self, what):
        self.fault = what

    def acknowledge(self):
        """Clear a latched fault. Output stays OFF afterwards."""
        self.fault = FAULT_NONE
        self._confirm = 0
        self._i_slow = 0.0
        self._i_fast = 0.0
