"""Firmware presets must equal what hardware/devices/tools/cc1101.py programs on the Pi (bench-proven)."""
import ctypes
import importlib.util
import os
import sys
import types
import pytest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firmwarelib  # noqa: E402

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


def load_cc1101_py():
    # cc1101.py imports spidev at module level; stub it so the maths is importable on the host
    if "spidev" not in sys.modules:
        spidev = types.ModuleType("spidev")
        class SpiDev:  # noqa: D401
            def open(self, *a): pass
            max_speed_hz = 0; mode = 0
            def xfer2(self, b): return [0] * len(b)
        spidev.SpiDev = SpiDev
        sys.modules["spidev"] = spidev
    spec = importlib.util.spec_from_file_location("cc1101py", os.path.join(TOOLS, "cc1101.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


class Recorder:
    """Stands in for cc1101.CC1101: records write_reg / patable writes in order."""
    def __init__(self):
        self.regs = {}; self.order = []; self.patable = None
        self.spi = self
    def write_reg(self, a, v): self.regs[a] = v; self.order.append((a, v))
    def strobe(self, c): pass
    def xfer2(self, b):                       # PATABLE burst write in configure_ook_tx
        if b and (b[0] & 0x3F) == 0x3E: self.patable = list(b[1:])
        return [0] * len(b)
    def read_status(self, a): return 0
    def get_marcstate(self): return 0x0D


@pytest.fixture(scope="module")
def lib():
    L = firmwarelib.build_c()
    L.cc_preset_regs.restype = ctypes.POINTER(ctypes.c_uint8)
    L.cc_preset_regs.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_size_t)]
    L.cc_preset_patable.restype = ctypes.POINTER(ctypes.c_uint8)
    L.cc_preset_patable.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_size_t)]
    L.cc_freq_regs.argtypes = [ctypes.c_double, ctypes.POINTER(ctypes.c_uint8)]
    L.cc_preset_by_name.restype = ctypes.c_int
    L.cc_preset_by_name.argtypes = [ctypes.c_char_p]
    return L


def c_preset(L, pid):
    n = ctypes.c_size_t()
    p = L.cc_preset_regs(pid, ctypes.byref(n))
    return {p[2 * i]: p[2 * i + 1] for i in range(n.value)}


def c_patable(L, pid):
    n = ctypes.c_size_t()
    p = L.cc_preset_patable(pid, ctypes.byref(n))
    return [p[i] for i in range(n.value)]


def test_fineoffset_preset_matches_cc1101_py(lib):
    m = load_cc1101_py(); r = Recorder()
    m.configure_fineoffset_fsk_rx(r, packet_length=25)        # the Pi's proven WS69 RX config (25-byte frames)
    assert c_preset(lib, 0) == r.regs, "CC_PRESET_FINEOFFSET_FSK differs from cc1101.py"


def test_ook_rx_preset_matches_cc1101_py(lib):
    m = load_cc1101_py(); r = Recorder()
    m.configure_ook_async_rx(r)
    assert c_preset(lib, 1) == r.regs, "CC_PRESET_OOK_RX differs from cc1101.py"


def test_ook_tx_presets_match_cc1101_py(lib):
    m = load_cc1101_py()
    for pid, rate in ((2, 100_000), (3, 4_000)):
        r = Recorder(); m.configure_ook_tx(r, chip_rate=rate)
        assert c_preset(lib, pid) == r.regs, "OOK TX preset %d differs" % pid
        assert c_patable(lib, pid) == r.patable == [0x00, 0xC0]


def test_freq_regs():
    L = firmwarelib.build_c()
    L.cc_freq_regs.argtypes = [ctypes.c_double, ctypes.POINTER(ctypes.c_uint8)]
    out = (ctypes.c_uint8 * 3)()
    for hz, exp in ((433.92e6, (0x10, 0xB0, 0x71)), (433.30e6, (0x10, 0xAA, 0x57)), (434.54e6, (0x10, 0xB6, 0x8C))):
        L.cc_freq_regs(hz, out)
        fw = round(hz * 65536 / 26e6)
        assert tuple(out) == ((fw >> 16) & 0xFF, (fw >> 8) & 0xFF, fw & 0xFF) == exp


def test_preset_names(lib):
    assert lib.cc_preset_by_name(b"fineoffset-fsk") == 0 and lib.cc_preset_by_name(b"ook-433") == 1
    assert lib.cc_preset_by_name(b"ook-tx-100k") == 2 and lib.cc_preset_by_name(b"ook-tx-4k") == 3
    assert lib.cc_preset_by_name(b"nope") == -1
