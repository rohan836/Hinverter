"""Persistent settings in /settings.json (flash). Loaded at boot.

All keys carry defaults; out-of-range or missing keys fall back to safe
defaults so a corrupt file can never wedge the inverter in a bad state.
"""

import json

_DEFAULTS = {
    "vout": 230,            # output voltage setting (modulation dial), volts
    "freq": 50,             # 50 or 60 Hz
    "icurrent_limit": 8.0,  # amps, output RMS trip (and 1.5x peak fast trip)
    "overtemp_c": 70.0,     # deg C, MLX90614 heatsink trip
    "lowbat_v": 10.8,       # volts, battery cutoff
}


def _validate(d):
    out = {}
    for k, default in _DEFAULTS.items():
        v = d.get(k, default)
        if k == "vout":
            v = int(v)
            v = min(240, max(100, v))
        elif k == "freq":
            v = int(v)
            v = v if v in (50, 60) else 50
        elif k == "icurrent_limit":
            v = float(v)
            v = min(20.0, max(0.5, v))
        elif k == "overtemp_c":
            v = float(v)
            v = min(110.0, max(30.0, v))
        elif k == "lowbat_v":
            v = float(v)
            v = min(13.0, max(9.0, v))
        out[k] = v
    return out


class Settings:
    def __init__(self, path="settings.json"):
        self.path = path
        self.data = dict(_DEFAULTS)

    def load(self):
        try:
            with open(self.path) as f:
                raw = json.load(f)
            self.data = _validate(raw if isinstance(raw, dict) else {})
        except Exception:
            self.data = dict(_DEFAULTS)
        return self.data

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data = _validate({**self.data, key: value})
        self.save()
