"""Pytest fixtures for decoder tests.

Run from the repo root or this directory:  uv run --with pytest pytest hardware/devices/esp32c3-cc1101-node/tests
"""
import pytest
from decoderlib import load, decode_bytes, decode_pulses, JSON_MAX  # noqa: F401


@pytest.fixture(scope="session")
def lib():
    return load()
