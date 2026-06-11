"""
Consumer-visible contract of list_cards() / find_card().

Parser correctness is owned by the Rust unit tests (decided — no
/proc/asound/cards test seam). These tests pin only the Python-facing
behaviour that is deterministic on any host.
"""

from __future__ import annotations

import os

import minimidi
import pytest

requires_proc_asound = pytest.mark.skipif(
    not os.path.exists("/proc/asound/cards"),
    reason="host has no /proc/asound/cards (no ALSA)",
)


@requires_proc_asound
def test_list_cards_shape() -> None:
    cards = minimidi.list_cards()
    assert isinstance(cards, list)
    for entry in cards:
        assert isinstance(entry, tuple)
        num, card_id = entry
        assert isinstance(num, int)
        assert num >= 0
        assert isinstance(card_id, str)
        assert card_id != ""
        # ALSA bracket padding must already be trimmed by the parser.
        assert card_id == card_id.strip()


@requires_proc_asound
def test_find_card_round_trips_listed_cards() -> None:
    cards = minimidi.list_cards()
    if not cards:
        pytest.skip("host has no ALSA cards registered")
    seen: set[str] = set()
    for num, card_id in cards:
        if card_id in seen:
            continue  # find_card returns the *first* match for duplicates
        seen.add(card_id)
        assert minimidi.find_card(card_id) == num


@requires_proc_asound
def test_find_card_unknown_id_raises() -> None:
    with pytest.raises(minimidi.MinimidiError, match="no-such-card-xyz-12345"):
        minimidi.find_card("no-such-card-xyz-12345")


@requires_proc_asound
def test_find_card_is_case_sensitive() -> None:
    cards = minimidi.list_cards()
    if not cards:
        pytest.skip("host has no ALSA cards registered")
    _num, card_id = cards[0]
    swapped = card_id.swapcase()
    if swapped == card_id or any(c == swapped for _, c in cards):
        pytest.skip("card id has no distinct case variant to test with")
    with pytest.raises(minimidi.MinimidiError):
        minimidi.find_card(swapped)
