"""
Shared fixtures for the minimidi unit test suite.

The fixtures open a real ``RawMidiOut`` against an ordinary temp file via the
hidden ``_open_path`` test hook, so the full Rust write path is
exercised end-to-end without needing ``snd-virmidi``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import minimidi
import pytest


class _OpenPath(Protocol):
    def __call__(self, path: str) -> minimidi.RawMidiOut: ...


def open_path(path: Path | str) -> minimidi.RawMidiOut:
    """
    Open a ``RawMidiOut`` against an arbitrary path via the test hook.

    ``_open_path`` is deliberately absent from the ``.pyi`` stubs, so we reach
    it with ``getattr`` + ``cast`` to keep ``mypy --strict`` quiet.
    """
    hook = cast(_OpenPath, getattr(minimidi.RawMidiOut, "_open_path"))  # noqa: B009
    return hook(str(path))


@pytest.fixture
def open_port() -> Callable[[Path | str], minimidi.RawMidiOut]:
    """
    Fixture wrapper around :func:`open_path` for tests that need to
    construct ports against arbitrary paths (FIFOs, read-only files, ...).
    """
    return open_path


@pytest.fixture
def capture_file(tmp_path: Path) -> Path:
    """
    An empty temp file that a fake port writes MIDI bytes into.
    """
    path = tmp_path / "midi-capture.bin"
    path.touch()
    return path


@pytest.fixture
def fake_port(capture_file: Path) -> minimidi.RawMidiOut:
    """
    A real RawMidiOut whose underlying fd is the capture temp file.
    """
    return open_path(capture_file)


@pytest.fixture
def read_new_bytes(capture_file: Path) -> Callable[[], bytes]:
    """
    Return a callable yielding bytes written to the capture file since the
    previous call (tracks a byte offset across calls).
    """
    offset = 0

    def _read() -> bytes:
        nonlocal offset
        data = capture_file.read_bytes()[offset:]
        offset += len(data)
        return data

    return _read
