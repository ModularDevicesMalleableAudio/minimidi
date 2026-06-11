"""
Context-manager protocol, close idempotency, and properties.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import minimidi
import pytest

OpenPort = Callable[[Path | str], minimidi.RawMidiOut]

# ---- context manager ---------------------------------------------------------


def test_enter_returns_port_and_exit_closes(open_port: OpenPort, capture_file: Path) -> None:
    port = open_port(capture_file)
    with port as entered:
        assert entered is port
        assert port.is_open
    assert not port.is_open


def test_writes_work_inside_with_block(
    open_port: OpenPort,
    capture_file: Path,
    read_new_bytes: Callable[[], bytes],
) -> None:
    with open_port(capture_file) as port:
        port.note_on(channel=16, note=60, velocity=100)
    assert read_new_bytes() == bytes([0x9F, 60, 100])


def test_exceptions_propagate_out_of_with_block(open_port: OpenPort, capture_file: Path) -> None:
    port = open_port(capture_file)
    with pytest.raises(RuntimeError, match="boom"):
        with port:
            raise RuntimeError("boom")
    # ...but the port still got closed on the way out.
    assert not port.is_open


# ---- close -------------------------------------------------------------------


def test_close_is_idempotent(fake_port: minimidi.RawMidiOut) -> None:
    assert fake_port.is_open
    fake_port.close()
    assert not fake_port.is_open
    fake_port.close()  # second close is a no-op, not an error
    assert not fake_port.is_open


def test_close_after_context_exit_is_noop(open_port: OpenPort, capture_file: Path) -> None:
    with open_port(capture_file) as port:
        pass
    port.close()
    assert not port.is_open


# ---- properties ----------------------------------------------------------------


def test_fake_port_properties(fake_port: minimidi.RawMidiOut) -> None:
    # _open_path ports carry the sentinel card_id/device.
    assert fake_port.card_id == "<custom>"
    assert fake_port.device == -1
    assert fake_port.is_open is True


def test_repr_reflects_state(fake_port: minimidi.RawMidiOut) -> None:
    assert "open" in repr(fake_port)
    assert "<custom>" in repr(fake_port)
    fake_port.close()
    assert "closed" in repr(fake_port)
