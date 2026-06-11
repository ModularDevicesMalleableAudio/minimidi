"""
Byte-pattern assertions per message type.

Each case returns ``(method_name, args, expected_bytes)``; the test drives the
method through a real RawMidiOut against the capture file and asserts the
exact bytes that reached the fd.
"""

from __future__ import annotations

from collections.abc import Callable

import minimidi
from pytest_cases import case, parametrize_with_cases

Case = tuple[str, tuple[int, ...], bytes]


@case
def case_note_on_ch1() -> Case:
    return "note_on", (1, 60, 100), bytes([0x90, 60, 100])


@case
def case_note_on_ch16() -> Case:
    return "note_on", (16, 60, 100), bytes([0x9F, 60, 100])


@case
def case_note_on_extremes() -> Case:
    return "note_on", (1, 0, 127), bytes([0x90, 0, 127])


@case
def case_note_off_ch1() -> Case:
    return "note_off", (1, 60), bytes([0x80, 60, 0])


@case
def case_note_off_ch16() -> Case:
    return "note_off", (16, 127), bytes([0x8F, 127, 0])


@case
def case_cc_ch1() -> Case:
    return "cc", (1, 0, 0), bytes([0xB0, 0, 0])


@case
def case_cc_ch16_cutoff() -> Case:
    return "cc", (16, 74, 64), bytes([0xBF, 74, 64])


@parametrize_with_cases("method, args, expected", cases=".")
def test_byte_patterns(
    method: str,
    args: tuple[int, ...],
    expected: bytes,
    fake_port: minimidi.RawMidiOut,
    read_new_bytes: Callable[[], bytes],
) -> None:
    getattr(fake_port, method)(*args)
    assert read_new_bytes() == expected


def test_consecutive_messages_concatenate(
    fake_port: minimidi.RawMidiOut,
    read_new_bytes: Callable[[], bytes],
) -> None:
    fake_port.note_on(channel=1, note=60, velocity=100)
    fake_port.note_off(channel=1, note=60)
    assert read_new_bytes() == bytes([0x90, 60, 100, 0x80, 60, 0])
