"""
Stub correctness: mypy --strict over a consumer example.

The positive example exercises every public method and import style; the
negative example proves the test-only ``_open_path`` hook is invisible to
consumers under ``mypy --strict``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EXAMPLE = """
import minimidi
from minimidi import MinimidiError, RawMidiOut, find_card, list_cards

port: minimidi.RawMidiOut = RawMidiOut("VirMIDI1", device=0)
port.note_on(channel=16, note=60, velocity=100)
port.note_off(channel=16, note=60)
port.cc(channel=16, controller=74, value=64)
port.send_bytes(bytes([0xE0, 0, 64]))
opened: bool = port.is_open
card: str = port.card_id
device: int = port.device
port.close()

with RawMidiOut("VirMIDI1") as ctx_port:
    ctx_port.note_on(channel=1, note=0, velocity=127)

cards: list[tuple[int, str]] = list_cards()
n: int = find_card("VirMIDI1")
err_type: type[Exception] = MinimidiError
public: list[str] = minimidi.__all__
version: str = minimidi.__version__
"""

NEGATIVE_EXAMPLE = """
from minimidi import RawMidiOut
RawMidiOut._open_path("/tmp/fake")
"""


def run_mypy_strict(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(script)],
        capture_output=True,
        text=True,
        cwd=script.parent,  # avoid picking up the repo's mypy `files` config
        check=False,
    )


def test_stubs_pass_mypy_strict(tmp_path: Path) -> None:
    script = tmp_path / "example.py"
    script.write_text(EXAMPLE)
    result = run_mypy_strict(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_test_hook_absent_from_public_stubs(tmp_path: Path) -> None:
    script = tmp_path / "negative.py"
    script.write_text(NEGATIVE_EXAMPLE)
    result = run_mypy_strict(script)
    assert result.returncode != 0
    assert "_open_path" in result.stdout + result.stderr
