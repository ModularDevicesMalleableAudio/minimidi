"""
Argument-range validation and error types.

Boundary matrices: channel ``0, 1, 16, 17``; data bytes ``-1, 0, 127, 128``;
device ``-1, 0``; write-after-close.
"""

from __future__ import annotations

from collections.abc import Callable

import minimidi
import pytest

# ---- channel boundaries ----------------------------------------------------


@pytest.mark.parametrize("channel", [0, 17, -1, 100])
@pytest.mark.parametrize("method", ["note_on", "note_off", "cc"])
def test_channel_out_of_range_rejected(
    method: str, channel: int, fake_port: minimidi.RawMidiOut
) -> None:
    args = (channel, 60, 100) if method != "note_off" else (channel, 60)
    with pytest.raises(minimidi.MinimidiError, match="channel"):
        getattr(fake_port, method)(*args)


@pytest.mark.parametrize("channel", [1, 16])
def test_channel_boundaries_accepted(
    channel: int,
    fake_port: minimidi.RawMidiOut,
    read_new_bytes: Callable[[], bytes],
) -> None:
    fake_port.note_on(channel, 60, 100)
    assert read_new_bytes() == bytes([0x90 | (channel - 1), 60, 100])


# ---- data-byte boundaries --------------------------------------------------


@pytest.mark.parametrize("bad", [-1, 128, 255])
def test_note_out_of_range_rejected(bad: int, fake_port: minimidi.RawMidiOut) -> None:
    with pytest.raises(minimidi.MinimidiError, match="note"):
        fake_port.note_on(1, bad, 100)
    with pytest.raises(minimidi.MinimidiError, match="note"):
        fake_port.note_off(1, bad)


@pytest.mark.parametrize("bad", [-1, 128, 255])
def test_velocity_out_of_range_rejected(bad: int, fake_port: minimidi.RawMidiOut) -> None:
    with pytest.raises(minimidi.MinimidiError, match="velocity"):
        fake_port.note_on(1, 60, bad)


@pytest.mark.parametrize("bad", [-1, 128, 255])
def test_controller_out_of_range_rejected(bad: int, fake_port: minimidi.RawMidiOut) -> None:
    with pytest.raises(minimidi.MinimidiError, match="controller"):
        fake_port.cc(1, bad, 64)


@pytest.mark.parametrize("bad", [-1, 128, 255])
def test_cc_value_out_of_range_rejected(bad: int, fake_port: minimidi.RawMidiOut) -> None:
    with pytest.raises(minimidi.MinimidiError, match="value"):
        fake_port.cc(1, 74, bad)


@pytest.mark.parametrize("good", [0, 127])
def test_data_byte_boundaries_accepted(
    good: int,
    fake_port: minimidi.RawMidiOut,
    read_new_bytes: Callable[[], bytes],
) -> None:
    fake_port.note_on(1, good, good)
    fake_port.cc(1, good, good)
    assert read_new_bytes() == bytes([0x90, good, good, 0xB0, good, good])


def test_nothing_written_when_validation_fails(
    fake_port: minimidi.RawMidiOut,
    read_new_bytes: Callable[[], bytes],
) -> None:
    with pytest.raises(minimidi.MinimidiError):
        fake_port.note_on(0, 60, 100)
    with pytest.raises(minimidi.MinimidiError):
        fake_port.note_on(1, 128, 100)
    assert read_new_bytes() == b""


# ---- constructor validation ------------------------------------------------


def test_negative_device_rejected_before_card_lookup() -> None:
    # device < 0 is rejected up front, so even a nonexistent card id never
    # reaches /proc/asound/cards parsing.
    with pytest.raises(minimidi.MinimidiError, match="device"):
        minimidi.RawMidiOut("no-such-card-xyz", device=-1)


def test_unknown_card_id_rejected() -> None:
    with pytest.raises(minimidi.MinimidiError, match="no-such-card-xyz"):
        minimidi.RawMidiOut("no-such-card-xyz", device=0)


# ---- write-after-close -----------------------------------------------------


def test_write_after_close_raises(fake_port: minimidi.RawMidiOut) -> None:
    fake_port.close()
    with pytest.raises(minimidi.MinimidiError, match="closed"):
        fake_port.note_on(1, 60, 100)
    with pytest.raises(minimidi.MinimidiError, match="closed"):
        fake_port.note_off(1, 60)
    with pytest.raises(minimidi.MinimidiError, match="closed"):
        fake_port.cc(1, 74, 64)
    with pytest.raises(minimidi.MinimidiError, match="closed"):
        fake_port.send_bytes(b"\x90\x3c\x64")


def test_minimidi_error_is_exception_subclass() -> None:
    assert issubclass(minimidi.MinimidiError, Exception)
