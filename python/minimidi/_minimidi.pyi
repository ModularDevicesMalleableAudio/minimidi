"""
Type stubs for the Rust-backed _minimidi extension module.

These are hand-written and the single source of truth for the package's
public type contract. The Rust source is the source of truth for runtime
behaviour; these stubs are the source of truth for static analysis.
"""

from __future__ import annotations

from types import TracebackType
from typing import final

class MinimidiError(Exception):
    """
    Raised on minimidi-specific errors.

    * Card ID not present in /proc/asound/cards
    * Argument out of valid range for typed helpers (channel,
      note/velocity/controller/value)
    * Operation on a closed port
    * ``send_bytes`` length out of range (1..=1024)

    Note that ``send_bytes`` with a non-``bytes`` argument raises
    ``TypeError``, not ``MinimidiError``.
    """

@final
class RawMidiOut:
    """
    A write-only Linux ALSA Raw MIDI output port.

    Opens ``/dev/snd/midiC<card_num>D<device>`` where ``card_num`` is
    resolved from ``card_id`` via /proc/asound/cards. Suitable for use with
    snd-virmidi virtual MIDI cards (and any other Raw MIDI capable card).

    ``device`` is typically 0-3 (``snd-virmidi`` default) or 0-7 (ALSA
    Raw MIDI max in mainline kernels). Out-of-range values raise
    ``FileNotFoundError`` at open time, not ``MinimidiError``.

    All channel arguments are 1-indexed (1..=16) to match common MIDI
    convention; the underlying status byte uses the 0..15 nibble.

    **Thread safety.** A single ``RawMidiOut`` is safe to share across
    Python threads; concurrent calls serialise inside an internal mutex.
    The GIL is released across the underlying ``write(2)`` syscall *and*
    across the mutex acquisition, so contention on a shared port never
    blocks unrelated Python work. One caveat: ``close()``, ``is_open``,
    and ``repr()`` acquire the same internal mutex while holding the GIL,
    so if another thread's write has stalled in the kernel (e.g. a wedged
    device), those calls block the interpreter until that write returns.

    **Closed is final.** Once ``close()``-d, a ``RawMidiOut`` cannot be
    reopened — there is no ``open()`` method. Write failures do **not**
    close the port: after a ``BrokenPipeError`` (or any ``OSError``) from
    a write, ``is_open`` remains ``True`` (it means "not explicitly
    closed", not "device alive") and retrying raises the underlying OS
    error again. To recover after device loss — e.g. a USB hot-replug or
    ``snd-virmidi`` reload — construct a new instance: this re-resolves
    the card index from /proc/asound/cards, which is the correct
    behaviour when the kernel may have re-numbered the card.
    """

    def __init__(self, card_id: str, device: int = 0) -> None: ...
    def note_on(self, channel: int, note: int, velocity: int) -> None: ...
    def note_off(self, channel: int, note: int) -> None: ...
    def cc(self, channel: int, controller: int, value: int) -> None: ...
    def send_bytes(self, data: bytes) -> None:
        """
        Write arbitrary MIDI bytes verbatim.

        ``data`` must be ``bytes``. ``bytearray``, ``memoryview``, ``str``,
        and ``list[int]`` all raise ``TypeError``. Length must be 1..=1024.
        No MIDI semantic validation is performed; bytes are written verbatim.
        """

    def close(self) -> None: ...
    def __enter__(self) -> RawMidiOut: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool: ...
    def __repr__(self) -> str: ...
    @property
    def card_id(self) -> str: ...
    @property
    def device(self) -> int: ...
    @property
    def is_open(self) -> bool: ...

def list_cards() -> list[tuple[int, str]]:
    """
    Return all ALSA cards as ``(card_number, card_id)`` tuples.

    Parses /proc/asound/cards. Returns an empty list if no cards are
    registered (very rare on any system with audio hardware).
    """

def find_card(card_id: str) -> int:
    """
    Look up the card_number for a given card_id.

    Matches minimidi's parsed card identifier **exactly**. ALSA's bracket
    padding is trimmed by the parser, but matching remains case-sensitive.
    Card ids are identifiers (set by the ALSA card driver / module params),
    not free text. Use :func:`list_cards` to enumerate the available
    identifiers minimidi will accept.

    Raises :class:`MinimidiError` if the id isn't present.
    """
