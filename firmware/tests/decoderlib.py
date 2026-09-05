"""Build decoders/*.c into build/libdecoders.so and call the decoders via ctypes.

No pytest dependency — used by both tests/conftest.py and tools/decode_fixture.py.
"""
import ctypes
import glob
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DECODERS = os.path.join(ROOT, "decoders")
BUILD = os.path.join(ROOT, "build")
SO = os.path.join(BUILD, "libdecoders.so")
CFLAGS = ["-std=c99", "-Wall", "-Wextra", "-Werror", "-O2", "-fPIC", "-shared"]
JSON_MAX = 512


def _build():
    os.makedirs(BUILD, exist_ok=True)
    srcs = sorted(glob.glob(os.path.join(DECODERS, "*.c")))
    cmd = ["cc", *CFLAGS, "-I", DECODERS, "-o", SO, *srcs]
    subprocess.run(cmd, check=True)


def decode_bytes(L, fn_name, data: bytes):
    """Call `int fn(const uint8_t*, size_t, char*, size_t)`; return (rc, parsed_json_or_None)."""
    fn = getattr(L, fn_name)
    fn.restype = ctypes.c_int
    fn.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
    buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
    out = ctypes.create_string_buffer(JSON_MAX)
    rc = fn(buf, len(data), out, JSON_MAX)
    return rc, (json.loads(out.value.decode()) if rc == 1 else None)


def decode_pulses(L, us):
    """Run ookpwm_decode over a whole train; return list of decoded dicts."""
    fn = L.ookpwm_decode
    fn.restype = ctypes.c_int
    fn.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
                   ctypes.c_char_p, ctypes.c_size_t]
    arr = (ctypes.c_uint32 * len(us))(*us)
    pos = ctypes.c_size_t(0)
    out = ctypes.create_string_buffer(JSON_MAX)
    results = []
    while True:
        rc = fn(arr, len(us), ctypes.byref(pos), out, JSON_MAX)
        if rc != 1:
            break
        results.append(json.loads(out.value.decode()))
    return results


def load() -> ctypes.CDLL:
    """Build, load libdecoders.so, and set up function signatures.

    Returns a ctypes.CDLL ready for use with decode_bytes() and decode_pulses().
    """
    _build()
    L = ctypes.CDLL(SO)
    L.rf_crc8.restype = ctypes.c_uint8
    L.rf_crc8.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_uint8, ctypes.c_uint8]
    L.rf_add_bytes.restype = ctypes.c_uint8
    L.rf_add_bytes.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
    L.rf_json_append.restype = ctypes.c_int
    # variadic: leave argtypes unset; callers pass ctypes-compatible values
    return L
