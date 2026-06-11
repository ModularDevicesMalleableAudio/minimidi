"""
Shared-port thread-safety smoke test.

A single RawMidiOut is shared across Python threads; concurrent calls must
serialise inside the internal mutex. This pins the public "safe to share"
contract — it is not a timing/GIL benchmark.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable

import minimidi

N_THREADS = 8
MSGS_PER_THREAD = 200
MSG_LEN = 3


def test_concurrent_writes_serialise_into_whole_messages(
    fake_port: minimidi.RawMidiOut,
    read_new_bytes: Callable[[], bytes],
) -> None:
    errors: list[Exception] = []

    def worker(thread_id: int) -> None:
        # Each thread writes a distinct, recognisable 3-byte message.
        payload = bytes([0x90, thread_id, 100])
        try:
            for _ in range(MSGS_PER_THREAD):
                fake_port.send_bytes(payload)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []

    data = read_new_bytes()
    assert len(data) == N_THREADS * MSGS_PER_THREAD * MSG_LEN

    # Every 3-byte chunk must be a whole, untorn message from one thread.
    counts: Counter[int] = Counter()
    for i in range(0, len(data), MSG_LEN):
        chunk = data[i : i + MSG_LEN]
        assert chunk[0] == 0x90
        assert chunk[2] == 100
        counts[chunk[1]] += 1

    assert counts == {i: MSGS_PER_THREAD for i in range(N_THREADS)}


def test_concurrent_close_and_write_is_safe(fake_port: minimidi.RawMidiOut) -> None:
    """
    Closing while other threads write must never crash; late writes either
    succeed or raise MinimidiError("write on closed...").
    """
    barrier = threading.Barrier(N_THREADS + 1)
    unexpected: list[Exception] = []

    def writer() -> None:
        barrier.wait()
        for _ in range(50):
            try:
                fake_port.send_bytes(b"\x90\x3c\x64")
            except minimidi.MinimidiError:
                return  # port closed underneath us — expected outcome
            except Exception as exc:
                unexpected.append(exc)
                return

    threads = [threading.Thread(target=writer) for _ in range(N_THREADS)]
    for t in threads:
        t.start()
    barrier.wait()
    fake_port.close()
    for t in threads:
        t.join()

    assert unexpected == []
    assert fake_port.is_open is False
