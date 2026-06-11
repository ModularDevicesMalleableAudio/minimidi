"""
Round-trip integration test (mechanism verified on real hardware).

Write known bytes to VirMIDI raw device 0; read them back from raw device 1
through the aconnect-wired sequencer route; assert exact byte equality.
"""

from __future__ import annotations

from collections.abc import Callable

import minimidi
import pytest


@pytest.mark.parametrize(
    ("method", "args", "expected"),
    [
        ("note_on", (16, 60, 100), bytes([0x9F, 60, 100])),
        ("note_off", (16, 60), bytes([0x8F, 60, 0])),
        ("cc", (16, 74, 64), bytes([0xBF, 74, 64])),
        ("send_bytes", (bytes([0xE0, 0x00, 0x40]),), bytes([0xE0, 0x00, 0x40])),
    ],
)
def test_message_roundtrip(
    method: str,
    args: tuple[object, ...],
    expected: bytes,
    wired_ports: tuple[int, str],
    read_loopback: Callable[[int], bytes],
) -> None:
    _, card_id = wired_ports
    with minimidi.RawMidiOut(card_id, device=0) as port:
        getattr(port, method)(*args)
        assert read_loopback(len(expected)) == expected


def test_burst_roundtrip(
    wired_ports: tuple[int, str],
    read_loopback: Callable[[int], bytes],
) -> None:
    """
    A run of mixed messages arrives intact and in order.
    """
    _, card_id = wired_ports
    expected = bytes([0x90, 60, 100, 0xB0, 74, 64, 0x80, 60, 0])
    with minimidi.RawMidiOut(card_id, device=0) as port:
        port.note_on(channel=1, note=60, velocity=100)
        port.cc(channel=1, controller=74, value=64)
        port.note_off(channel=1, note=60)
        assert read_loopback(len(expected)) == expected


def test_find_card_resolves_virmidi(virmidi_card: tuple[int, str]) -> None:
    num, card_id = virmidi_card
    assert minimidi.find_card(card_id) == num
