"""Build firmware/src/cc1101_node C sources (+ decoders) into build/libfirmware.so, and the C++ radio
host harnesses build/radio_host (CC1101) and build/sx1278_host (SX1278). No pytest dependency."""
import ctypes
import glob
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # firmware/ (parent of tests/)
FW = os.path.join(ROOT, "src", "cc1101_node")
DEC = os.path.join(ROOT, "decoders")
BUILD = os.path.join(ROOT, "build")
SO = os.path.join(BUILD, "libfirmware.so")
RADIO_HOST = os.path.join(BUILD, "radio_host")
SX1278_HOST = os.path.join(BUILD, "sx1278_host")
CFLAGS = ["-std=c99", "-Wall", "-Wextra", "-Werror", "-O2", "-fPIC", "-shared"]


def build_c():
    os.makedirs(BUILD, exist_ok=True)
    srcs = sorted(glob.glob(os.path.join(FW, "*.c"))) + sorted(glob.glob(os.path.join(FW, "secplus", "*.c"))) \
        + sorted(glob.glob(os.path.join(DEC, "*.c")))
    subprocess.run(["cc", *CFLAGS, "-I", DEC, "-I", FW, "-o", SO, *srcs], check=True)
    return ctypes.CDLL(SO)


def build_radio_host():
    os.makedirs(BUILD, exist_ok=True)
    subprocess.run(["c++", "-std=c++14", "-Wall", "-Wextra", "-Werror", "-O1", "-I", FW, "-I", DEC,
                    "-o", RADIO_HOST, os.path.join(FW, "cc1101_radio.cpp"), os.path.join(FW, "cc1101_presets.c"),
                    os.path.join(HERE, "radio_host.cpp")], check=True)
    return RADIO_HOST


def build_sx1278_host():
    os.makedirs(BUILD, exist_ok=True)
    subprocess.run(["c++", "-std=c++14", "-Wall", "-Wextra", "-Werror", "-O1", "-I", FW,
                    "-o", SX1278_HOST, os.path.join(FW, "sx1278_radio.cpp"),
                    os.path.join(HERE, "sx1278_host.cpp")], check=True)
    return SX1278_HOST
