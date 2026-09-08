"""CC1101Radio against a fake bus: SPI framing, preset load, RX entry, small TX."""
import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firmwarelib  # noqa: E402


def host(*args):
    exe = firmwarelib.build_radio_host()
    out = subprocess.run([exe, *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def test_identify_reads_partnum_version_with_read_burst():
    r = host("identify")
    assert r == {"ok": 1, "part": 0, "ver": 0x14}


def test_load_preset_writes_every_register():
    r = host("load", "0")
    assert len(r["regs"]) >= 30 and r["regs"]["6"] == 25          # PKTLEN 25 for WS69


def test_enter_rx_strobes_idle_flush_cal_rx():
    r = host("enter_rx")
    assert r["ok"] == 1
    strobes = [b for b in r["log"] if b in ("36", "3a", "33", "34")]
    assert strobes[:3] == ["36", "3a", "33"] and strobes[-1] == "34"   # SIDLE, SFRX, SCAL ... SRX


def test_tx_small_uses_fixed_length_and_fifo_burst():
    r = host("tx_small")
    assert r["ok"] == 1 and r["pktlen"] == 3 and r["pktctrl0"] == 0
    assert "7f" in r["log"]          # FIFO burst write address 0x3F|0x40
    assert "35" in r["log"]          # STX
