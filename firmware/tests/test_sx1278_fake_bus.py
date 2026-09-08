"""SX1278Radio against a fake bus + fake reset line: RegVersion identify, SPI framing, reset pulse.

Mirrors test_radio_fake_bus.py (the CC1101 equivalent)."""
import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firmwarelib  # noqa: E402


def host(*args):
    exe = firmwarelib.build_sx1278_host()
    out = subprocess.run([exe, *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def test_identify_reads_regversion_0x42_read_framing():
    r = host("identify")
    assert r["ok"] == 1 and r["ver"] == 0x12
    # read RegVersion: select, address 0x42 (bit7=0 -> read), dummy byte, deselect
    assert r["log"] == ["S", "42", "00", "D"]


def test_identify_rejects_wrong_version():
    r = host("identify_bad")
    assert r == {"ok": 0, "ver": 0}


def test_write_reg_sets_address_bit7():
    r = host("write_reg")
    assert r["reg1"] == 0x0A
    # write RegOpMode(0x01): address byte is 0x01|0x80 = 0x81, then the value 0x0a
    assert r["log"] == ["S", "81", "0a", "D"]


def test_read_reg_clears_address_bit7_and_returns_value():
    r = host("read_reg")
    assert r["val"] == 0x6C
    assert r["log"] == ["S", "06", "00", "D"]   # 0x06 has bit7 clear -> read


def test_reset_pulses_low_then_high():
    r = host("reset")
    assert r["rst"] == ["L", "H"]               # active-low: assert then release


def test_fsk_tx_preset_and_fifo_framing():
    tx = host("transmit", "510f5c5401")         # 5-byte payload
    assert tx["ok"] == 1
    # ends back in FSK standby; PA on PA_BOOST +17 dBm; FIFO-not-empty TX start; fixed-len packet
    assert tx["opmode"] == 0x09
    assert tx["pa_config"] == 0x8F
    assert tx["pa_ramp"] == 0x09
    assert tx["fifothresh"] == 0x80
    assert tx["packetconfig1"] == 0x00 and tx["packetconfig2"] == 0x40
    assert tx["payloadlength"] == 5
    assert tx["preamble_lsb"] == 5
    assert tx["sync1"] == 0x2D and tx["sync2"] == 0xD4
    assert tx["diomapping1"] == 0x00
    # FIFO burst write: select, 0x80 (RegFifo|write), the 5 payload bytes in order, deselect.
    log = tx["log"]
    frame = ["S", "80", "51", "0f", "5c", "54", "01", "D"]
    assert any(log[i:i + len(frame)] == frame for i in range(len(log))), log


def test_fsk_tx_power_is_configurable():
    # SxTxPower drives RegPaConfig: 0x8F=+17 dBm (default), 0x82=+4 dBm (low, for co-located tests).
    assert host("transmit", "510f5c5401")["pa_config"] == 0x8F          # default
    assert host("transmit", "510f5c5401", "0x82")["pa_config"] == 0x82  # low-power override


def test_fsk_tx_modem_matches_rx_preset():
    # The TX preset must use the same bitrate/fdev/carrier/sync as the RX preset so a peer node's
    # configure_fineoffset_fsk() receiver can decode what we transmit (on-air compatibility).
    tx = host("transmit", "510f5c5401")
    rx = host("configure")
    for k in ("br_msb", "br_lsb", "fdev_msb", "fdev_lsb", "frf_msb", "sync1", "sync2"):
        assert tx[k] == rx[k], (k, tx[k], rx[k])
