"""PC-side tests for the HW-040 encoder logic (mocked machine.Pin + time).

Drives the gray-code table decoder and button debounce with scripted
transitions to prove no phantom counts from bounce and correct short/long.
"""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class FakeTicks:
    def __init__(self):
        self.now_ms = 0


class FakePin:
    IN = 0
    PULL_UP = 0
    IRQ_RISING = 1
    IRQ_FALLING = 2
    OUT = 1

    def __init__(self, pin_id, mode=None, pull=None, value=None):
        self.pin_id = pin_id
        self._value = 1
        self.handler = None

    def value(self, v=None):
        if v is None:
            return self._value
        self._value = v

    def irq(self, trigger=None, handler=None):
        self.handler = handler


def make_modules():
    ticks = FakeTicks()
    machine = types.ModuleType("machine")
    machine.Pin = FakePin
    time_mod = types.ModuleType("time")
    time_mod.ticks_ms = lambda: ticks.now_ms
    time_mod.ticks_us = lambda: ticks.now_ms * 1000
    time_mod.ticks_diff = lambda a, b: a - b
    time_mod.sleep_us = lambda us: None
    time_mod.sleep_ms = lambda ms: None
    sys.modules["machine"] = machine
    sys.modules["time"] = time_mod
    return ticks


def load_encoder():
    ticks = make_modules()
    # encoder caches its `time` module object at import; drop it so each
    # test gets an encoder bound to THIS test's fake time/machine.
    sys.modules.pop("encoder", None)
    import encoder
    return encoder, ticks


def transition(e, clk, dt):
    e._clk._value = clk
    e._dt._value = dt
    e._edge(None)


def test_full_cw_detents():
    encoder, _ = load_encoder()
    e = encoder.Encoder()
    # two full clockwise sequences: 00 -> 01 -> 11 -> 10 -> 00, twice
    for _ in range(2):
        transition(e, 0, 0)
        transition(e, 0, 1)
        transition(e, 1, 1)
        transition(e, 1, 0)
        transition(e, 0, 0)
    ev = e.poll()
    assert ev == ("rotate", 2), ev
    print("cw detents ok")


def test_full_ccw_detents():
    encoder, _ = load_encoder()
    e = encoder.Encoder()
    # counter-clockwise: 00 -> 10 -> 11 -> 01 -> 00
    for _ in range(3):
        transition(e, 0, 0)
        transition(e, 1, 0)
        transition(e, 1, 1)
        transition(e, 0, 1)
        transition(e, 0, 0)
    ev = e.poll()
    assert ev == ("rotate", -3), ev
    print("ccw detents ok")


def test_bounce_produces_no_counts():
    encoder, _ = load_encoder()
    e = encoder.Encoder()
    # bounce around a fixed position: invalid transitions must be discarded
    for seq in ((0, 0), (0, 1), (0, 0), (0, 1), (0, 0), (1, 0), (0, 0), (1, 0), (0, 0)):
        transition(e, *seq)
    ev = e.poll()
    assert ev is None, ev
    print("bounce rejection ok")


def test_partial_sequence_no_count():
    encoder, _ = load_encoder()
    e = encoder.Encoder()
    # only half a sequence: must not count
    transition(e, 0, 1)
    transition(e, 1, 1)
    assert e.poll() is None
    print("partial sequence ok")


def test_button_short_and_long():
    encoder, ticks = load_encoder()
    e = encoder.Encoder()

    ticks.now_ms += 10
    e._sw._value = 0            # pressed
    assert e.poll() is None     # debounce window not reached yet on next call
    ticks.now_ms += 50
    e.poll()                    # registers press after debounce
    ticks.now_ms += 200         # hold 200 ms
    e._sw._value = 1            # release
    ticks.now_ms += 50
    assert e.poll() == ("short",)

    # long press: hold beyond 1500 ms
    ticks.now_ms += 10
    e._sw._value = 0
    ticks.now_ms += 50
    e.poll()                    # press registered
    ticks.now_ms += 1600        # hold past threshold
    assert e.poll() == ("long",)
    e._sw._value = 1            # release; must not emit another long/short
    ticks.now_ms += 50
    assert e.poll() is None
    print("button short/long ok")


def test_button_bounce_rejected():
    encoder, ticks = load_encoder()
    e = encoder.Encoder()
    # press at t=1000: accepted (edge debounce 30 ms), press registered
    ticks.now_ms = 1000
    e._sw._value = 0
    assert e.poll() is None        # held, no release yet
    # bounce: release/press flips within the 30 ms window -> ignored
    ticks.now_ms += 5              # 1005
    e._sw._value = 1               # bounce release
    assert e.poll() is None
    ticks.now_ms += 5              # 1010
    e._sw._value = 0               # bounce press
    assert e.poll() is None
    # real release after the window: accepted as a short press
    ticks.now_ms += 50             # 1060
    e._sw._value = 1
    assert e.poll() == ("short",)
    print("button bounce rejection ok")


if __name__ == "__main__":
    test_full_cw_detents()
    test_full_ccw_detents()
    test_bounce_produces_no_counts()
    test_partial_sequence_no_count()
    test_button_short_and_long()
    test_button_bounce_rejected()
    print("ALL ENCODER TESTS PASSED")
