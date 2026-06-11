# minimidi

Minimal Linux ALSA Raw MIDI **output**, written in Rust (PyO3), fully typed for Python 3.13+.

`minimidi` does one thing: open an ALSA Raw MIDI device (`/dev/snd/midiC*D*`) write-only
and send MIDI bytes to it. No input, no sequencer scheduling, no SysEx framing, no
cross-platform abstraction — just note-on / note-off / CC helpers and a raw-bytes
escape hatch, shipped as a single `abi3` wheel with no system dependencies.

- **Linux only** (ALSA Raw MIDI).
- **Output only.**
- **Typed.** PEP 561 `py.typed` + hand-written stubs; clean under `mypy --strict`.
- **Thread-safe.** One port can be shared across Python threads; writes serialise
  internally and release the GIL across the `write(2)` syscall.

See [`AGENTS.md`](./AGENTS.md) for developer / agent workflow instructions.

## Install

Not yet published to PyPI. Build from source (needs Rust stable +
[uv](https://docs.astral.sh/uv/)):

```bash
uv sync --all-groups
uv run maturin develop --release
```

## Quick start

```python
import minimidi

with minimidi.RawMidiOut("VirMIDI", device=0) as port:
    port.note_on(channel=1, note=60, velocity=100)   # middle C on
    port.cc(channel=1, controller=74, value=64)      # filter cutoff
    port.note_off(channel=1, note=60)                # note off (velocity 0)
# port auto-closes on context exit
```

Channels are **1-indexed** (1–16), matching common MIDI convention. Notes,
velocities, controllers, and values are 0–127. Out-of-range arguments raise
`MinimidiError` before anything is written.

## Finding your card

Ports are addressed by ALSA card id (the bracketed name in `/proc/asound/cards`)
plus a raw device number:

```python
import minimidi

minimidi.list_cards()
# [(0, "PCH"), (1, "VirMIDI"), (3, "pisound")]

minimidi.find_card("pisound")
# 3 — raises MinimidiError if not present

port = minimidi.RawMidiOut("pisound", device=0)
# opens /dev/snd/midiC3D0 write-only
```

Card-id matching is exact and case-sensitive (ALSA's bracket padding is trimmed).
`device` is typically 0–3 for `snd-virmidi`; a non-existent device raises
`FileNotFoundError` at open time.

## Escape hatch: raw bytes

Messages without a first-class helper (pitch bend, program change, aftertouch, ...)
can be written verbatim:

```python
channel = 1
port.send_bytes(bytes([0xE0 | (channel - 1), 0x00, 0x40]))  # pitch bend, centre
```

`send_bytes` accepts only `bytes` (not `bytearray`/`memoryview`/`str`), length
1–1024, and performs **no MIDI semantic validation** — the caller owns correctness.

## Errors and recovery

| Condition | Exception |
|---|---|
| Unknown card id, out-of-range argument, write on closed port | `MinimidiError` |
| Device node missing, no permission, device disappeared mid-write | `FileNotFoundError` / `PermissionError` / `BrokenPipeError` (standard errno-derived `OSError` subclasses) |
| Non-`bytes` payload to `send_bytes` | `TypeError` |

A failed write does **not** close the port: `is_open` means "not explicitly
closed", and a retry raises the same OS error again. After device loss (USB
hot-replug, module reload), construct a *new* `RawMidiOut` — that re-resolves the
card number from `/proc/asound/cards`, which is correct when the kernel may have
re-numbered the card. Closed is final: there is no `open()`/reopen method.

## Testing without hardware

Load the kernel's virtual Raw MIDI card and `minimidi` can talk to it like any
other device:

```bash
sudo modprobe snd-virmidi        # persistent: echo snd-virmidi | sudo tee /etc/modules-load.d/virmidi.conf
```

```python
port = minimidi.RawMidiOut("VirMIDI", device=0)
```

## Development

```bash
uv sync --all-groups               # venv + dev deps
uv run maturin develop --release   # build the Rust extension into the venv
./scripts/test.sh                  # cargo test + ruff + mypy + pytest
```

Integration tests (`tests/integration/`) need `snd-virmidi` loaded and `aconnect`
(alsa-utils) installed; they skip cleanly otherwise.

## License

MIT — see [`LICENSE`](./LICENSE).
