"""
Integration fixtures: VirMIDI cross-device loopback wiring.

Verified mechanism (tested on a target Raspberry Pi, 2026-06-11): VirMIDI
raw writes do NOT loop back to the same device's read side — they go out the
device's sequencer port only. So the round-trip wires VirMIDI port 0 →
port 1 with aconnect, writes raw to D0, and reads raw from D1.

Everything here skips (never fails) when snd-virmidi or aconnect is missing.
"""

from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator

import minimidi
import pytest

READ_DEADLINE_S = 2.0


def virmidi_present() -> bool:
    try:
        with open("/proc/asound/cards") as f:
            return "VirMIDI" in f.read()
    except FileNotFoundError:
        return False


@pytest.fixture(scope="session", autouse=True)
def _require_virmidi() -> None:
    if not virmidi_present():
        pytest.skip("snd-virmidi not loaded; load with `sudo modprobe snd-virmidi`")
    if shutil.which("aconnect") is None:
        pytest.skip("aconnect not found; install alsa-utils")


@pytest.fixture(scope="session")
def virmidi_card() -> tuple[int, str]:
    """
    (card_number, card_id) of the first VirMIDI card on the host.
    """
    for num, card_id in minimidi.list_cards():
        if card_id.startswith("VirMIDI"):
            return num, card_id
    pytest.skip("no VirMIDI card id found in list_cards()")


def _seq_client(card_num: int, dev: int, aconnect_listing: str) -> int:
    """
    Sequencer client number for VirMIDI raw device `dev` of `card_num`.

    aconnect -l names these clients 'Virtual Raw MIDI <card>-<dev>'.
    """
    pattern = rf"client (\d+): 'Virtual Raw MIDI {card_num}-{dev}'"
    match = re.search(pattern, aconnect_listing)
    if match is None:
        pytest.skip(f"sequencer client for VirMIDI {card_num}-{dev} not found")
    return int(match.group(1))


@pytest.fixture(scope="session")
def wired_ports(virmidi_card: tuple[int, str]) -> Iterator[tuple[int, str]]:
    """
    aconnect VirMIDI port 0 → port 1 for the session; undo on teardown.

    Yields (card_number, card_id); tests write raw to device 0 and read raw
    from device 1.
    """
    card_num, card_id = virmidi_card
    if not os.path.exists(f"/dev/snd/midiC{card_num}D1"):
        pytest.skip("VirMIDI loaded with fewer than 2 raw devices (need midi_devs>=2)")

    listing = subprocess.run(["aconnect", "-l"], capture_output=True, text=True, check=True).stdout
    sender = _seq_client(card_num, 0, listing)
    receiver = _seq_client(card_num, 1, listing)

    subprocess.run(["aconnect", f"{sender}:0", f"{receiver}:0"], check=True)
    try:
        yield card_num, card_id
    finally:
        subprocess.run(["aconnect", "-d", f"{sender}:0", f"{receiver}:0"], check=False)


@pytest.fixture
def read_loopback(wired_ports: tuple[int, str]) -> Iterator[Callable[[int], bytes]]:
    """
    Reader on the raw read side of VirMIDI device 1.

    Opens O_RDONLY|O_NONBLOCK, drains stale bytes (the host may have
    pre-existing subscriptions feeding the port), and yields a callable that
    reads exactly `n` bytes with a select() deadline.
    """
    card_num, _ = wired_ports
    rfd = os.open(f"/dev/snd/midiC{card_num}D1", os.O_RDONLY | os.O_NONBLOCK)

    def drain() -> None:
        try:
            while os.read(rfd, 4096):
                pass
        except BlockingIOError:
            pass

    def read_exact(n: int) -> bytes:
        got = b""
        deadline = time.monotonic() + READ_DEADLINE_S
        while len(got) < n and time.monotonic() < deadline:
            ready, _, _ = select.select([rfd], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(rfd, 4096)
                except BlockingIOError:
                    continue
                got += chunk
        return got

    drain()
    try:
        yield read_exact
    finally:
        os.close(rfd)
