"""
The raw escape-hatch path.

``send_bytes()`` validates only type (``bytes``) and length (1..=1024).
No MIDI semantic validation: arbitrary payloads are written verbatim.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import minimidi
import pytest

# ---- verbatim pass-through (no MIDI semantic validation) --------------------


@pytest.mark.parametrize(
    "payload",
    [
        bytes([0xE0, 0x00, 0x40]),  # pitch bend — not a first-class method
        bytes([0xF8]),  # realtime clock, single byte
        bytes([0xFF]),  # reset, max status byte
        bytes([0x00]),  # bare data byte, not valid MIDI — still written
        bytes([0x01, 0x02, 0x03, 0x04]),  # nonsense sequence — still written
        bytes(range(256)) * 4,  # 1024 bytes, max length
        b"\x90",  # 1 byte, min length
    ],
)
def test_payload_written_verbatim(
    payload: bytes,
    fake_port: minimidi.RawMidiOut,
    read_new_bytes: Callable[[], bytes],
) -> None:
    fake_port.send_bytes(payload)
    assert read_new_bytes() == payload


# ---- length validation -------------------------------------------------------


def test_empty_payload_rejected(fake_port: minimidi.RawMidiOut) -> None:
    with pytest.raises(minimidi.MinimidiError, match="length"):
        fake_port.send_bytes(b"")


def test_oversize_payload_rejected(fake_port: minimidi.RawMidiOut) -> None:
    with pytest.raises(minimidi.MinimidiError, match="length"):
        fake_port.send_bytes(b"\x00" * 1025)


def test_max_length_payload_accepted(
    fake_port: minimidi.RawMidiOut,
    read_new_bytes: Callable[[], bytes],
) -> None:
    payload = b"\x42" * 1024
    fake_port.send_bytes(payload)
    assert read_new_bytes() == payload


# ---- type validation (bytes only — deliberate v0.1 choice) ------------------


@pytest.mark.parametrize(
    "bad",
    [
        bytearray(b"\x90\x3c\x64"),
        memoryview(b"\x90\x3c\x64"),
        "\x90<d",
        [0x90, 0x3C, 0x64],
        0x90,
        None,
    ],
)
def test_non_bytes_rejected_with_typeerror(bad: Any, fake_port: minimidi.RawMidiOut) -> None:
    with pytest.raises(TypeError, match="bytes"):
        fake_port.send_bytes(bad)


def test_type_check_precedes_length_check(fake_port: minimidi.RawMidiOut) -> None:
    # An *empty* bytearray fails on type, not on length: TypeError, not
    # MinimidiError (type check precedes length check).
    with pytest.raises(TypeError):
        fake_port.send_bytes(bytearray())  # type: ignore[arg-type]  # deliberate bad type


def test_nothing_written_on_rejected_payload(
    fake_port: minimidi.RawMidiOut,
    read_new_bytes: Callable[[], bytes],
) -> None:
    with pytest.raises(minimidi.MinimidiError):
        fake_port.send_bytes(b"")
    with pytest.raises(TypeError):
        fake_port.send_bytes(bytearray(b"\x90"))  # type: ignore[arg-type]  # deliberate bad type
    assert read_new_bytes() == b""
