"""
minimidi — minimal Linux ALSA Raw MIDI output.

See README.md for usage examples.
"""

from __future__ import annotations

from ._minimidi import (
    MinimidiError,
    RawMidiOut,
    find_card,
    list_cards,
)

__all__ = ["MinimidiError", "RawMidiOut", "find_card", "list_cards"]
__version__ = "0.1.0"
