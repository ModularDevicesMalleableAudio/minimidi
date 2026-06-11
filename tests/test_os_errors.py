"""
OS-level errors must surface as errno-derived Python exception subclasses,
and write failures must not mutate port state (deliberate design decision).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import minimidi
import pytest

OpenPort = Callable[[Path | str], minimidi.RawMidiOut]


def test_open_missing_path_raises_file_not_found(open_port: OpenPort, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_port(tmp_path / "does-not-exist")


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permissions")
def test_open_unwritable_path_raises_permission_error(open_port: OpenPort, tmp_path: Path) -> None:
    locked = tmp_path / "read-only.bin"
    locked.touch()
    locked.chmod(0o444)
    with pytest.raises(PermissionError):
        open_port(locked)


def test_broken_pipe_surfaces_and_does_not_close_port(open_port: OpenPort, tmp_path: Path) -> None:
    """
    Deterministic BrokenPipeError via a FIFO whose reader has gone away.

    Open the read end non-blocking, open the port on the write end, close the
    reader, then write: the kernel returns EPIPE. The port must remain
    logically open (is_open means "not explicitly closed", not "device
    alive") and a retry must raise the underlying OS error again — never
    MinimidiError.
    """
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        port = open_port(fifo)
    finally:
        os.close(rfd)

    with pytest.raises(BrokenPipeError):
        port.send_bytes(b"\x90\x3c\x64")

    # Decided contract: write errors don't mutate port state.
    assert port.is_open is True

    # Retry raises the real OS error again, not "write on closed RawMidiOut".
    with pytest.raises(BrokenPipeError):
        port.note_on(channel=1, note=60, velocity=100)

    # Explicit close still works afterwards.
    port.close()
    assert port.is_open is False
    with pytest.raises(minimidi.MinimidiError, match="closed"):
        port.send_bytes(b"\x90\x3c\x64")


def test_fifo_write_with_live_reader_succeeds(open_port: OpenPort, tmp_path: Path) -> None:
    """
    Sanity check of the FIFO fixture itself: with a live reader the write
    path works and delivers exact bytes.
    """
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        port = open_port(fifo)
        port.note_on(channel=1, note=60, velocity=100)
        assert os.read(rfd, 16) == bytes([0x90, 60, 100])
        port.close()
    finally:
        os.close(rfd)
