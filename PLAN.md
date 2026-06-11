# `minimidi`: minimal Rust-backed Python MIDI library

> Extracted from a sequencer webapp whose MIDI surface is tiny (write-only
> Linux ALSA Raw MIDI, three message types) and where the only viable Python
> wrapper for that surface — `python-rtmidi` — is a stale single-maintainer
> C extension with no PyPI release since 2023-11. Rather than vendor 50
> lines of brittle `os.write` shim inside the consumer app, we extract a
> focused, Rust-backed library that we (and anyone else) can depend on as a
> normal PyPI package.

## Phase status

```
Phase 0 — Repo + skeleton + first wheel:      ✅ Complete
Phase 1 — Public API + Python type stubs:     ✅ Complete
Phase 2 — CI + cibuildwheel + first release:  ⏳ Not started
Phase 3 — downstream consumer cutover:        ⏳ Not started
Phase 4 — Docs + 1.0 freeze:                  ⏳ Not started
```

---

## 1. Goal

A small, durable, fully-typed Python library that opens ALSA Raw MIDI
output ports and sends three message types (note-on, note-off, CC).
Written in Rust with `pyo3` bindings, distributed as `abi3` wheels so a
single artefact serves Python 3.13, 3.14, 3.15, and any future 3.x.

The library exists because **the existing options are wrong for a
minimal use case**:

| Option | Problem |
|---|---|
| `python-rtmidi` | 2.5y since last PyPI release (1.5.8, 2023-11); maintainer accepts patches but doesn't publish; ceiling at Python 3.12 wheels; needs source build for ≥3.13. |
| `pyalsa` (Debian apt) | Hard-pinned to Pi OS bookworm's Python 3.11; not on PyPI. |
| `pyalsa` from git | Active upstream but requires `libasound2-dev` + Cython source build at install; complicates bootstrap. |
| `os.write` shim in the consumer app | ~50 LOC of code we'd have to maintain inside the consumer app, no reuse, no semantic versioning, no testing infrastructure of its own. |
| `mido` + any backend | Same underlying problem (depends on rtmidi or portmidi). |

`minimidi` exists for projects that:

- run on Linux only (or accept Linux-only behaviour),
- only need to **write** raw MIDI bytes,
- want forward-compatible Python version support (3.13+),
- need full type-checking against the public API,
- want a wheel install (no system deps, no build at install time).

---

## 2. Scope

### In scope (v0.x → v1.0)

- **Linux ALSA Raw MIDI output only** — writes to `/dev/snd/midiC<card>D<device>` directly via the kernel character-device interface. No ALSA C library dependency.
- **Three MIDI message types:** note-on, note-off, CC (Control Change).
- **One escape hatch:** `send_bytes(data)` for any well-formed MIDI byte sequence the caller constructs themselves, so callers aren't blocked when they need a status byte we don't expose.
- **Synchronous I/O.** Each method call blocks until the kernel accepts the bytes. Internally the GIL is released across the `write(2)` syscall.
- **Card lookup helpers:** `list_cards()` and `find_card(card_id)` for resolving `/proc/asound/cards` entries to numeric card indices (no shelling out to `aconnect`).
- **PEP 561 typed:** ship `py.typed` marker + hand-written `.pyi` stubs covering 100 % of the public surface.
- **abi3 wheels:** built with `abi3-py313`. One wheel per platform serves 3.13, 3.14, 3.15, and beyond.

### Explicit non-goals

| Not in scope | Reason |
|---|---|
| **MIDI input / reading** | The downstream consumer doesn't need it. Adding async input doubles the surface area and brings threading concerns. |
| **SysEx** | Not needed downstream. Can be added later as an opt-in method without breaking the existing API. |
| **MIDI clock / MTC / song-position generation** | Out of scope; clock generation belongs in a sequencer, not a transport. |
| **Pitch bend, aftertouch, program change** | Not currently needed downstream. Trivial to add via `send_bytes()` in the meantime; first-class methods can land in a later minor release. |
| **Cross-platform (macOS, Windows)** | Linux-only by design. The library will fail to import cleanly on other OSes with a clear `OSError`. |
| **ALSA Sequencer API** | We use Raw MIDI deliberately: it requires no client registration, no `aconnect` orchestration from the Python side, and works with persistent `snd-virmidi` ports. |
| **`asyncio` integration** | Calls are short kernel syscalls (µs-scale). Wrap with `asyncio.to_thread()` at the call site if needed; not the library's job. |
| **`mido` compatibility shim** | If `mido` interop is wanted later, a small `minimidi.mido_backend` extra can be added. Out of v1.0 scope. |
| **MIDI 2.0 (UMP)** | MIDI 1.0 only. |

### Acceptance criteria for v1.0

- Wheel for `manylinux_2_28` x86_64 and aarch64, available on PyPI.
- Single `abi3` wheel installs and works on Python 3.13, 3.14, 3.15.
- `mypy --strict` clean against the public API from a consumer's perspective.
- Round-trip integration test: write known bytes to one VirMIDI raw device → read them back from a second VirMIDI raw device wired via `aconnect` → assert byte equality.
- The downstream consumer's `midi_bridge.py` imports `minimidi` instead of `rtmidi` with no semantic change to the bridge's behaviour.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ Python consumer (sequencer webapp, others)                       │
│                                                                  │
│   import minimidi                                                │
│   port = minimidi.RawMidiOut("VirMIDI1", device=0)               │
│   port.note_on(channel=16, note=60, velocity=100)                │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   ▼  (via PyO3 ABI3 boundary)
┌──────────────────────────────────────────────────────────────────┐
│ minimidi/_minimidi.<abi3>.so   (Rust extension, ~250 LoC)        │
│                                                                  │
│   #[pyclass] RawMidiOut { file: Mutex<Option<File>>, ... }       │
│   #[pymethods] impl RawMidiOut {                                 │
│       fn note_on(&self, ...) { validate; locked_gil_released; }  │
│       ...                                                        │
│   }                                                              │
│                                                                  │
│   fn find_card(card_id: &str) -> Result<i32, MinimidiError> {    │
│       // parse /proc/asound/cards                                │
│   }                                                              │
└──────────────────┬───────────────────────────────────────────────┘
                   │  std::fs / Linux syscalls
                   ▼
        /dev/snd/midiC<N>D<M>   (kernel character device)
                   │
                   ▼  (virmidi propagates to sequencer side)
        client N in `aconnect -l`
                   │
                   ▼
        Subscribed downstream consumer (e.g. PD via aconnect)
```

### Why Rust + PyO3?

| Reason | Detail |
|---|---|
| **GIL release across syscall** | `Python::allow_threads` lets other Python work proceed during the kernel write. Pure Python `os.write` holds the GIL. For a webapp routing many concurrent inputs, this matters. |
| **Thread-safe by construction** | `RawMidiOut` wraps its `File` in `Mutex<Option<File>>` and all methods take `&self`. A single port instance can be shared between Python threads; writes serialise inside the mutex. No PyO3 `Already borrowed` runtime errors, no per-call-site locking dance for consumers. |
| **Zero runtime Python deps** | No Cython, no `libasound2-dev` at install. Just an `.so`. |
| **One wheel forward-compatible** | `abi3-py313` means we don't rebuild for every new Python minor release; one wheel works on 3.13, 3.14, 3.15, and onwards. |
| **Memory-safe byte construction** | Rust's type system catches off-by-one or wrong-byte mistakes at compile time. The whole library is small enough that the entire byte path can be formally enumerated and tested. |
| **Distributable as a binary** | `maturin` + `cibuildwheel` produces ARM64 and x86_64 wheels in CI. No build-from-source dance on the Pi. |
| **Future expansion** | If we later add SysEx chunking, async I/O, or the ALSA Sequencer API, Rust gives us the headroom without rewriting the language. |

### Why **not** Rust for the consumer-side API surface

The Python side stays idiomatic: `RawMidiOut`, `note_on(channel, note, velocity)`, context manager, properties. The Rust extension is implementation detail; consumers should never need to know it's not pure Python.

---

## 4. Public Python API

Final surface for v1.0:

```python
import minimidi

# --- Card lookup ----------------------------------------------------------

cards: list[tuple[int, str]] = minimidi.list_cards()
# [(0, "PCH"), (3, "pisound"), (10, "VirMIDI1"), (11, "VirMIDI2"), ...]

card_num: int = minimidi.find_card("VirMIDI1")   # → 10
# raises MinimidiError if not present.
# Match is exact against minimidi's parsed card id (case-sensitive after
# trimming ALSA's bracket padding); use list_cards() to see the available
# identifiers verbatim.

# --- Port lifecycle -------------------------------------------------------

port = minimidi.RawMidiOut("VirMIDI1", device=0)
# Equivalent to opening /dev/snd/midiC10D0 in write mode.
# Raises MinimidiError if the card_id isn't present, or PermissionError /
# FileNotFoundError from the underlying open(2) syscall.
#
# Closed-is-final: once close()-d, an instance cannot be reopened.
# Write failures do NOT change port state: after a BrokenPipeError (or any
# OSError) from a write, is_open remains True — it means "not explicitly
# closed", not "device alive" — and a retry raises the underlying OS error
# again rather than MinimidiError.
# To recover after BrokenPipeError or a USB hot-replug, construct a new
# RawMidiOut(card_id, device) — this re-resolves the card index from
# /proc/asound/cards, which is the correct behaviour when the kernel may
# have re-numbered the card.

with minimidi.RawMidiOut("VirMIDI1", device=0) as port:
    port.note_on(channel=16, note=60, velocity=100)
    port.note_off(channel=16, note=60)
    port.cc(channel=16, controller=74, value=64)
# Auto-closes on context exit.

port.close()                  # explicit close
port.is_open                  # bool property
port.card_id                  # str property (e.g. "VirMIDI1")
port.device                   # int property (e.g. 0)

# --- Message helpers (all 1-indexed channels: 1..16) ----------------------

port.note_on(channel: int, note: int, velocity: int) -> None
port.note_off(channel: int, note: int) -> None            # always vel=0
port.cc(channel: int, controller: int, value: int) -> None

# --- Escape hatch ---------------------------------------------------------

port.send_bytes(data: bytes) -> None
# Caller is responsible for the bytes being well-formed MIDI.
# minimidi performs no MIDI semantic validation here: any bytes payload of
# length 1..=1024 is written verbatim, including status bytes >= 0x80 and
# otherwise nonsensical MIDI sequences. Useful for messages minimidi doesn't
# expose as first-class methods (pitch bend, aftertouch, program change, etc.).
#
# `data` MUST be `bytes`. `bytearray`, `memoryview`, `str`, and `list[int]`
# all raise TypeError. This is a deliberate v0.1 choice (see §14 Q5) to
# avoid copy-ambiguity questions; relaxing it later is non-breaking.

# --- Exceptions -----------------------------------------------------------

class MinimidiError(Exception): ...
# Base class for minimidi-specific errors:
#   * card_id not found
#   * value out of range for typed helpers (channel not 1..16;
#     note/velocity/controller/value not 0..127)
#   * send_bytes length out of range (not 1..=1024)
#   * write to closed port
#
# OS-level errors (file not found, permission denied, broken pipe on
# device disappearance) propagate as the standard built-in exceptions
# (FileNotFoundError, PermissionError, BrokenPipeError, OSError), preserving
# the normal errno-derived subclass where Python provides one.
```

### Validation rules (`MinimidiError` unless a different exception is noted)

| Argument | Valid range |
|---|---|
| `channel` | 1 ≤ channel ≤ 16 |
| `note` | 0 ≤ note ≤ 127 |
| `velocity` | 0 ≤ velocity ≤ 127 |
| `controller` | 0 ≤ controller ≤ 127 |
| `value` | 0 ≤ value ≤ 127 |
| `device` | 0 ≤ device (no upper bound enforced — opening a non-existent `/dev/snd/midiC*D*` raises `FileNotFoundError`). Typically 0–3 for `snd-virmidi`, 0–7 for ALSA Raw MIDI in mainline kernels |
| `card_id` | non-empty string, must match a line in `/proc/asound/cards` |
| `data` (send_bytes) | `bytes` (not `bytearray`, `memoryview`, `str`, or `list[int]`), 1 ≤ len ≤ 1024; no MIDI semantic validation |

### `send_bytes` rationale

We deliberately ship one untyped escape hatch so the library never becomes a blocker. If a consumer ever needs pitch bend before we land `port.pitch_bend()`, it can call:

```python
port.send_bytes(bytes([0xE0 | (ch - 1) & 0x0F, lsb, msb]))
```

`send_bytes()` deliberately validates only type and length. It does not reject bytes above `0x7F`, incomplete messages, realtime bytes, or otherwise malformed MIDI; the caller owns correctness for this escape hatch.

This is the *only* place the consumer needs to know MIDI status bytes. Every other API call hides them.

---

## 5. Internal implementation

### 5.1 Rust crate (`src/lib.rs`, ≈ 250 LoC)

```rust
use pyo3::prelude::*;
use pyo3::exceptions::PyTypeError;
use pyo3::create_exception;
use pyo3::types::{PyBytes, PyType};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;

create_exception!(_minimidi, MinimidiError, pyo3::exceptions::PyException);

// ---- Validation -----------------------------------------------------------

fn validate_channel(channel: i32) -> PyResult<u8> {
    if !(1..=16).contains(&channel) {
        return Err(MinimidiError::new_err(
            format!("channel must be 1..=16, got {channel}")));
    }
    Ok((channel - 1) as u8)  // → MIDI's 0..15 channel nibble
}

fn validate_data_byte(value: i32, name: &str) -> PyResult<u8> {
    if !(0..=127).contains(&value) {
        return Err(MinimidiError::new_err(
            format!("{name} must be 0..=127, got {value}")));
    }
    Ok(value as u8)
}

// ---- Card lookup ----------------------------------------------------------

// Pure parser — takes the file contents directly. Fully unit-testable from
// Rust without touching the filesystem. All synthetic-input parser tests
// (typical format, multi-digit indices, malformed lines, etc.) live in the
// #[cfg(test)] module against this function.
fn parse_cards_content(raw: &str) -> Vec<(i32, String)> {
    // /proc/asound/cards format:
    //   " 10 [VirMIDI        ]: VirMIDI - VirMIDI\n  long-name-here"
    // We grab the index and the bracketed id.
    let mut cards = Vec::new();
    for line in raw.lines() {
        if let Some((num, rest)) = line.trim_start().split_once(' ') {
            if let Ok(n) = num.parse::<i32>() {
                if let Some(start) = rest.find('[') {
                    if let Some(end) = rest[start + 1..].find(']') {
                        let id = rest[start + 1..start + 1 + end].trim().to_string();
                        cards.push((n, id));
                    }
                }
            }
        }
    }
    cards
}

// Thin I/O wrapper around the pure parser.
fn parse_cards() -> std::io::Result<Vec<(i32, String)>> {
    let raw = std::fs::read_to_string("/proc/asound/cards")?;
    Ok(parse_cards_content(&raw))
}

#[pyfunction]
fn list_cards() -> PyResult<Vec<(i32, String)>> {
    parse_cards().map_err(PyErr::from)
}

#[pyfunction]
fn find_card(card_id: &str) -> PyResult<i32> {
    let cards = parse_cards().map_err(PyErr::from)?;
    // Exact, case-sensitive match against the parsed card id. parse_cards_content()
    // trims ALSA's bracket padding, so callers should use list_cards() to see
    // the identifiers minimidi will accept.
    cards.iter()
        .find(|(_, id)| id == card_id)
        .map(|(n, _)| *n)
        .ok_or_else(|| MinimidiError::new_err(
            format!("ALSA card '{card_id}' not found in /proc/asound/cards")))
}

// ---- RawMidiOut ----------------------------------------------------------

#[pyclass]
struct RawMidiOut {
    // Mutex makes the port safe to share across Python threads; the fd is
    // wrapped in an Option so close() can drop it without consuming self.
    // The mutex is acquired *inside* allow_threads (see write() below) so a
    // contending thread blocks without holding the GIL.
    file: Mutex<Option<File>>,
    #[pyo3(get)] card_id: String,
    #[pyo3(get)] device: i32,
}

#[pymethods]
impl RawMidiOut {
    #[new]
    #[pyo3(signature = (card_id, device=0))]
    fn new(card_id: String, device: i32) -> PyResult<Self> {
        if device < 0 {
            return Err(MinimidiError::new_err(
                format!("device must be ≥ 0, got {device}")));
        }
        // No upper bound on device — a non-existent /dev/snd/midiC*D* path
        // surfaces as FileNotFoundError from open(2), which is the right
        // error in that situation.
        let card_num = find_card(&card_id)?;
        let path: PathBuf = format!("/dev/snd/midiC{card_num}D{device}").into();
        // Use PyErr::from(std::io::Error) so errno-derived subclasses
        // survive (FileNotFoundError, PermissionError, etc.).
        let file = OpenOptions::new()
            .write(true)
            .open(&path)
            .map_err(PyErr::from)?;
        Ok(Self {
            file: Mutex::new(Some(file)),
            card_id,
            device,
        })
    }

    /// Test-only constructor: open `path` directly, bypassing card lookup.
    /// Underscore-prefixed and absent from the .pyi stubs, so consumers
    /// under `mypy --strict` cannot accidentally depend on it. Used by the
    /// test suite to point a RawMidiOut at a regular temp-file fake without
    /// requiring `snd-virmidi`. Not part of the stable API.
    #[classmethod]
    fn _open_path(_cls: &Bound<'_, PyType>, path: &str) -> PyResult<Self> {
        // Use PyErr::from(std::io::Error) so errno-derived subclasses
        // survive in tests as well as production paths.
        let file = OpenOptions::new()
            .write(true)
            .open(path)
            .map_err(PyErr::from)?;
        Ok(Self {
            file: Mutex::new(Some(file)),
            card_id: "<custom>".to_string(),
            device: -1,
        })
    }

    #[getter]
    fn is_open(&self) -> bool {
        self.file.lock().unwrap_or_else(|e| e.into_inner()).is_some()
    }

    fn note_on(&self, py: Python<'_>, channel: i32, note: i32, velocity: i32)
        -> PyResult<()>
    {
        let ch = validate_channel(channel)?;
        let n  = validate_data_byte(note, "note")?;
        let v  = validate_data_byte(velocity, "velocity")?;
        self.write(py, &[0x90 | ch, n, v])
    }

    fn note_off(&self, py: Python<'_>, channel: i32, note: i32) -> PyResult<()> {
        let ch = validate_channel(channel)?;
        let n  = validate_data_byte(note, "note")?;
        self.write(py, &[0x80 | ch, n, 0])
    }

    fn cc(&self, py: Python<'_>, channel: i32, controller: i32, value: i32)
        -> PyResult<()>
    {
        let ch = validate_channel(channel)?;
        let c  = validate_data_byte(controller, "controller")?;
        let v  = validate_data_byte(value, "value")?;
        self.write(py, &[0xB0 | ch, c, v])
    }

    fn send_bytes(&self, py: Python<'_>, data: &Bound<'_, PyAny>) -> PyResult<()> {
        // Strict type check: only `bytes` is accepted. `bytearray`,
        // `memoryview`, `str`, list[int] etc. all raise TypeError. The
        // type check precedes the length check so type errors take
        // priority. See §14 Q5 — v0.1 ships bytes-only deliberately.
        let bytes = data.downcast::<PyBytes>().map_err(|_| PyTypeError::new_err(
            "send_bytes: data must be `bytes` (not bytearray, memoryview, str, or list)"
        ))?;
        let slice: &[u8] = bytes.as_bytes();
        if slice.is_empty() || slice.len() > 1024 {
            return Err(MinimidiError::new_err(
                format!("send_bytes: length must be 1..=1024, got {}", slice.len())));
        }
        self.write(py, slice)
    }

    fn close(&self) -> PyResult<()> {
        let mut guard = self.file.lock().unwrap_or_else(|e| e.into_inner());
        *guard = None;   // Drop closes the fd. Idempotent: already-None stays None.
        Ok(())
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> { slf }

    fn __exit__(
        &self,
        _exc_type: PyObject,
        _exc_val: PyObject,
        _exc_tb: PyObject,
    ) -> PyResult<bool> {
        self.close()?;
        Ok(false)   // don't suppress exceptions
    }

    fn __repr__(&self) -> String {
        let state = if self.is_open() { "open" } else { "closed" };
        format!("<minimidi.RawMidiOut card_id='{}' device={} {}>",
                self.card_id, self.device, state)
    }
}

// Non-pymethods impl block for private helpers.
impl RawMidiOut {
    fn write(&self, py: Python<'_>, bytes: &[u8]) -> PyResult<()> {
        // Release the GIL *before* taking the mutex, so a thread contending
        // for the same port blocks on the mutex without holding the GIL.
        // Mutex poisoning is ignored: write_all is the only operation under
        // the lock and doesn't panic in normal use.
        py.allow_threads(|| {
            let mut guard = self.file.lock().unwrap_or_else(|e| e.into_inner());
            let file = guard.as_mut().ok_or_else(||
                MinimidiError::new_err("write on closed RawMidiOut"))?;
            file.write_all(bytes)
                .map_err(PyErr::from)
        })
    }
}

// ---- Module entrypoint ---------------------------------------------------

#[pymodule]
fn _minimidi(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RawMidiOut>()?;
    m.add_function(wrap_pyfunction!(list_cards, m)?)?;
    m.add_function(wrap_pyfunction!(find_card, m)?)?;
    m.add("MinimidiError", py.get_type::<MinimidiError>())?;
    Ok(())
}
```

This is the *complete* Rust implementation. ~250 LoC including blank lines and comments. The five key design decisions baked in:

1. **`Mutex<Option<File>>` + `&self` methods.** Safe to share a single `RawMidiOut` between Python threads. Mutex acquired inside `allow_threads` so contending threads block off-GIL.
2. **Closed is final.** No `open()` method on the instance. Reopen = construct fresh (re-resolves the card index, correct across hot-replug).
3. **Parser split into pure + I/O.** `parse_cards_content(&str)` is fully unit-testable from Rust without touching `/proc`. The I/O wrapper exists only to feed it.
4. **`_open_path` test hook.** Underscore-prefixed classmethod that opens a path directly. Not in `__all__`, not in `.pyi` stubs; visible to the test suite, invisible to `mypy --strict` consumers.
5. **Write errors don't mutate port state.** `write()` returns the OS error without touching the `Option<File>`; `is_open` stays `True` and a retry hits the kernel again. No error-classification policy, no masking of the real failure behind `MinimidiError` on subsequent calls.

### 5.2 `Cargo.toml`

```toml
[package]
name        = "minimidi"
version     = "0.1.0"
edition     = "2021"
license     = "MIT"
description = "Minimal Linux ALSA Raw MIDI output, with Python bindings via PyO3"
repository  = "https://github.com/<owner>/minimidi"
readme      = "README.md"

[lib]
name       = "_minimidi"          # match #[pymodule] name in lib.rs
crate-type = ["cdylib"]           # cdylib = dynamic library for Python to load

[dependencies]
pyo3 = { version = "0.23", features = ["extension-module", "abi3-py313"] }
```

The `abi3-py313` feature is **load-bearing**: it tells PyO3 to link against the stable Python ABI, capped at the 3.13 surface. The resulting `.so` runs on **any** Python ≥3.13, including 3.14 and 3.15 — without rebuilding. This is the single most important configuration choice in the project.

### 5.3 Python wrapper (`python/minimidi/__init__.py`)

The Rust extension exposes everything via `_minimidi`. The pure-Python wrapper layer is mostly re-exports plus the public `__all__` and `__version__`:

```python
"""minimidi — minimal Linux ALSA Raw MIDI output.

See README.md for usage examples.
"""
from __future__ import annotations

from ._minimidi import (
    RawMidiOut,
    MinimidiError,
    list_cards,
    find_card,
)

__all__ = ["RawMidiOut", "MinimidiError", "list_cards", "find_card"]
__version__ = "0.1.0"
```

No Python logic. The wrapper exists solely to:
1. Provide a stable public import path (`minimidi.RawMidiOut` rather than `minimidi._minimidi.RawMidiOut`).
2. Anchor the `py.typed` PEP 561 marker.
3. Host the future home of any pure-Python convenience helpers (none in v1.0).

---

## 6. Type stubs

Hand-written stubs in `python/minimidi/_minimidi.pyi`:

```python
"""Type stubs for the Rust-backed _minimidi extension module.

These are hand-written and the single source of truth for the package's
public type contract. The Rust source is the source of truth for runtime
behaviour; these stubs are the source of truth for static analysis.
"""
from __future__ import annotations
from types import TracebackType
from typing import final

class MinimidiError(Exception):
    """Raised on minimidi-specific errors.

    * Card ID not present in /proc/asound/cards
    * Argument out of valid range for typed helpers (channel,
      note/velocity/controller/value)
    * Operation on a closed port
    * ``send_bytes`` length out of range (1..=1024)

    Note that ``send_bytes`` with a non-``bytes`` argument raises
    ``TypeError``, not ``MinimidiError``.
    """
    ...

@final
class RawMidiOut:
    """A write-only Linux ALSA Raw MIDI output port.

    Opens ``/dev/snd/midiC<card_num>D<device>`` where ``card_num`` is
    resolved from ``card_id`` via /proc/asound/cards. Suitable for use with
    snd-virmidi virtual MIDI cards (and any other Raw MIDI capable card).

    ``device`` is typically 0–3 (``snd-virmidi`` default) or 0–7 (ALSA
    Raw MIDI max in mainline kernels). Out-of-range values raise
    ``FileNotFoundError`` at open time, not ``MinimidiError``.

    All channel arguments are 1-indexed (1..=16) to match common MIDI
    convention; the underlying status byte uses the 0..15 nibble.

    **Thread safety.** A single ``RawMidiOut`` is safe to share across
    Python threads; concurrent calls serialise inside an internal mutex.
    The GIL is released across the underlying ``write(2)`` syscall *and*
    across the mutex acquisition, so contention on a shared port never
    blocks unrelated Python work.

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
        """Write arbitrary MIDI bytes verbatim.

        ``data`` must be ``bytes``. ``bytearray``, ``memoryview``, ``str``,
        and ``list[int]`` all raise ``TypeError``. Length must be 1..=1024.
        No MIDI semantic validation is performed; bytes are written verbatim.
        """
        ...
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
    """Return all ALSA cards as ``(card_number, card_id)`` tuples.

    Parses /proc/asound/cards. Returns an empty list if no cards are
    registered (very rare on any system with audio hardware).
    """
    ...

def find_card(card_id: str) -> int:
    """Look up the card_number for a given card_id.

    Matches minimidi's parsed card identifier **exactly**. ALSA's bracket
    padding is trimmed by the parser, but matching remains case-sensitive.
    Card ids are identifiers (set by the ALSA card driver / module params),
    not free text. Use :func:`list_cards` to enumerate the available
    identifiers minimidi will accept.

    Raises :class:`MinimidiError` if the id isn't present.
    """
    ...
```

Companion `python/minimidi/py.typed` (zero-byte file required by PEP 561).

### Stub testing

A dedicated `tests/test_stubs.py` imports `minimidi` and runs `mypy --strict` against an example script. CI re-runs this against every supported Python version (3.13, 3.14, 3.15) to catch stub drift.

---

## 7. Project structure

```
minimidi/
├── README.md
├── LICENSE                          # MIT
├── CHANGELOG.md
├── CONTRIBUTING.md
├── .gitignore
├── .python-version                  # uv reads this; pinned to 3.13
├── Cargo.toml
├── Cargo.lock                       # committed (reproducible builds)
├── pyproject.toml
├── uv.lock                          # committed
├── src/
│   └── lib.rs                       # Rust extension (≈ 200 LoC)
├── python/
│   └── minimidi/
│       ├── __init__.py
│       ├── _minimidi.pyi            # type stubs
│       └── py.typed                 # PEP 561 marker
├── tests/
│   ├── test_validation.py           # range checks, error types
│   ├── test_messages.py             # byte-pattern assertions per message type
│   ├── test_cards.py                # list_cards / find_card behaviour
│   ├── test_context_manager.py      # __enter__/__exit__ + close idempotency
│   ├── test_send_bytes.py           # raw escape-hatch path
│   ├── test_os_errors.py            # errno-derived Python exception subclasses
│   ├── test_threading.py            # shared-port thread-safety smoke test
│   ├── test_stubs.py                # mypy --strict over example script
│   └── integration/
│       ├── conftest.py              # skip if virmidi/aconnect absent; port wiring fixture
│       └── test_roundtrip.py        # write VirMIDI D0, read D1 (aconnect-wired)
└── .github/
    └── workflows/
        ├── ci.yml                   # lint + tests + cargo test + wheel build
        └── release.yml              # cibuildwheel + PyPI trusted publishing
```

### `pyproject.toml`

```toml
[build-system]
requires      = ["maturin>=1.7,<2.0"]
build-backend = "maturin"

[project]
name            = "minimidi"
version         = "0.1.0"
description     = "Minimal Linux ALSA Raw MIDI output, with Python bindings via PyO3"
requires-python = ">=3.13"
readme          = "README.md"
license         = { text = "MIT" }
authors         = [{ name = "<owner>", email = "<email>" }]
keywords        = ["midi", "alsa", "linux", "rust", "pyo3"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "Programming Language :: Python :: 3.15",
    "Programming Language :: Rust",
    "Topic :: Multimedia :: Sound/Audio :: MIDI",
    "Typing :: Typed",
]

[project.urls]
Homepage   = "https://github.com/<owner>/minimidi"
Repository = "https://github.com/<owner>/minimidi"
Issues     = "https://github.com/<owner>/minimidi/issues"
Changelog  = "https://github.com/<owner>/minimidi/blob/main/CHANGELOG.md"

[tool.maturin]
python-source = "python"             # mixed Rust+Python project layout
module-name   = "minimidi._minimidi"
features      = ["pyo3/extension-module"]
strip         = true

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cases>=3.8",
    "mypy>=1.11",
    "ruff>=0.6",
    "maturin>=1.7",
]

[tool.ruff]
line-length    = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "W", "UP", "RUF"]

[tool.mypy]
python_version       = "3.13"
strict               = true
warn_unused_ignores  = true
files                = ["python/minimidi", "tests"]
```

### `.gitignore`

```
target/                     # Cargo build artefacts
*.so                        # compiled extension
__pycache__/
.mypy_cache/
.pytest_cache/
.ruff_cache/
.venv/
dist/
build/
*.egg-info/
.python-version-cache       # uv cache files (paranoia)
```

### `.python-version`

```
3.13
```

(`uv` reads this and installs python-build-standalone 3.13 automatically.)

---

## 8. Build & developer workflow

All commands run from the repo root.

### First-time setup on a contributor's machine

```bash
# Install uv (once per machine).
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Rust toolchain (once per machine).
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Clone + sync.
git clone https://github.com/<owner>/minimidi
cd minimidi
uv sync --all-groups        # creates .venv, installs dev deps
```

### Build the Rust extension into the dev venv

```bash
uv run maturin develop --release
# Now `import minimidi` works in `uv run python` / `uv run pytest`.
```

`maturin develop` compiles `src/lib.rs` into `python/minimidi/_minimidi.<abi3>.so` and installs it editable in the venv. Re-run after any Rust change.

### Quality gates (run in this order; all must pass)

```bash
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest                # unit tests
cargo test                   # Rust unit tests
cargo clippy -- -D warnings  # Rust lint
cargo fmt --check
```

### Build a release wheel locally

```bash
uv run maturin build --release
# Produces target/wheels/minimidi-<version>-cp313-abi3-<platform>.whl
```

---

## 9. Tests

### 9.1 Rust unit tests (`src/lib.rs` — `#[cfg(test)] mod tests`)

Test byte-pattern correctness for every message type, validation edge cases,
and the pure `/proc/asound/cards` parser. These don't need Python; `cargo
test` runs them in seconds. To keep `cargo test` free of libpython linking
(the CI rust job has no Python toolchain), validation lives in pure
`check_*` functions returning `Result<u8, String>`, with thin
`validate_*` adapters converting to `PyResult` via `MinimidiError::new_err`;
the `#[cfg(test)]` module only exercises the pure layer.

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn note_on_byte_pattern() {
        // Channel 1 = nibble 0; channel 16 = nibble F.
        // Cannot test write() directly without a file; test the validate
        // path and assemble bytes inline for assertion.
        let ch = validate_channel(1).unwrap();
        assert_eq!([0x90 | ch, 60, 100], [0x90, 60, 100]);

        let ch = validate_channel(16).unwrap();
        assert_eq!([0x90 | ch, 60, 100], [0x9F, 60, 100]);
    }

    #[test]
    fn channel_out_of_range_rejected() {
        Python::with_gil(|_py| {
            assert!(validate_channel(0).is_err());
            assert!(validate_channel(17).is_err());
            assert!(validate_channel(-1).is_err());
        });
    }

    #[test]
    fn data_byte_out_of_range_rejected() {
        Python::with_gil(|_py| {
            assert!(validate_data_byte(-1, "x").is_err());
            assert!(validate_data_byte(128, "x").is_err());
            assert!(validate_data_byte(255, "x").is_err());
        });
    }

    #[test]
    fn parse_cards_handles_typical_proc_format() {
        // Embed a known-good sample of /proc/asound/cards in the test;
        // assert (index, id) pairs, including multi-digit indices.
    }

    #[test]
    fn parse_cards_ignores_malformed_lines() {
        // Missing bracket pairs, blank lines, long-name continuation lines,
        // and non-numeric prefixes should not panic and should not emit cards.
    }

    #[test]
    fn parse_cards_trims_bracket_padding_but_preserves_inner_id_case() {
        // "[VirMIDI        ]" becomes "VirMIDI"; matching remains
        // case-sensitive in find_card().
    }

    #[test]
    fn duplicate_card_ids_keep_proc_order() {
        // parse_cards_content returns duplicates in file order; find_card()
        // therefore returns the first matching card via .find().
    }
}
```

### 9.2 Python unit tests (`tests/`)

These exercise the public API and are the spec for consumer-visible behaviour. Use `pytest-cases` for parametrised matrices so the byte-pattern assertions read as data.

`tests/test_messages.py`:

```python
from __future__ import annotations
from collections.abc import Callable

from pytest_cases import case, parametrize_with_cases

import minimidi

# Each case returns (method_name, args, expected_bytes).
@case
def case_note_on_ch1():
    return "note_on", (1, 60, 100), bytes([0x90, 60, 100])

@case
def case_note_on_ch16():
    return "note_on", (16, 60, 100), bytes([0x9F, 60, 100])

@case
def case_note_off_ch1():
    return "note_off", (1, 60), bytes([0x80, 60, 0])

@case
def case_cc_ch16_cutoff():
    return "cc", (16, 74, 64), bytes([0xBF, 74, 64])

@parametrize_with_cases("method, args, expected", cases=".")
def test_byte_patterns(
    method: str,
    args: tuple[int, ...],
    expected: bytes,
    fake_port: minimidi.RawMidiOut,
    read_new_bytes: Callable[[], bytes],
) -> None:
    getattr(fake_port, method)(*args)
    assert read_new_bytes() == expected
```

The `fake_port` and `read_new_bytes` fixtures are defined in `tests/conftest.py`. They use the underscore-prefixed test hook `RawMidiOut._open_path(path)` (§5.1) to open a real `RawMidiOut` against an ordinary empty temp file created by `tmp_path`, so the write path is exercised end-to-end without needing VirMIDI for unit tests and without FIFO open-order deadlocks. `read_new_bytes` keeps a byte offset into that temp file; after each method call it opens the file for reading, seeks to the previous offset, reads newly written bytes, advances the offset, and returns those bytes. The same fixtures are used across `test_validation.py`, `test_send_bytes.py`, and `test_context_manager.py`.

Note that `_open_path` is deliberately not in the `.pyi` stubs (§6), so consumer code under `mypy --strict` cannot accidentally take a dependency on it. Tests reach for it via `getattr(minimidi.RawMidiOut, "_open_path")` to keep the type-checker quiet inside the test suite.

Concrete Python unit-test coverage required before Phase 1 exits:

- `test_messages.py`: note-on, note-off, and CC byte patterns for channel 1
  and channel 16.
- `test_validation.py`: boundary matrices for `channel` (`0, 1, 16, 17`),
  `note` / `velocity` / `controller` / `value` (`-1, 0, 127, 128`),
  `device` (`-1, 0`), and write-after-`close()`.
- `test_send_bytes.py`: accepts arbitrary `bytes` payloads without MIDI
  semantic validation, including status bytes `>= 0x80` and nonsensical
  sequences; rejects `b""` and length `1025` with `MinimidiError`; rejects
  `bytearray`, `memoryview`, `str`, and `list[int]` with `TypeError` before
  any length check.
- `test_context_manager.py`: `with RawMidiOut...` returns the port, closes on
  exit, does not suppress exceptions, and `close()` is idempotent.
- `test_cards.py`: parser correctness is owned by the Rust unit tests
  (decided — no `/proc/asound/cards` test seam; the parser is pure and fully
  covered by `cargo test`, which CI always runs alongside pytest). Python-level
  tests assert the consumer-visible contract only: `list_cards()` returns
  `list[tuple[int, str]]` on the host; when at least one card exists,
  `find_card(list_cards()[0][1])` returns that card's number; and
  `find_card("no-such-card-xyz")` raises `MinimidiError` deterministically.
- `test_os_errors.py`: `_open_path()` on a missing path raises
  `FileNotFoundError`. Broken pipe is triggered deterministically with a FIFO:
  `os.mkfifo`, open the read end, `_open_path()` the write end, close the read
  end, then write — the write raises `BrokenPipeError`; assert `is_open` is
  still `True` afterwards and that a retry raises `BrokenPipeError` again (not
  `MinimidiError`) per the decided write-errors-don't-mutate-state contract.
  Permission-denied is covered with a `chmod 0o444` temp file when running as
  a non-root user. These tests guard the requirement that `std::io::Error` is
  converted in a way that preserves Python's errno-derived exception
  subclasses.
- `test_threading.py`: share one `RawMidiOut` across several Python threads,
  have each write a short labelled byte message, and assert all writes complete
  without PyO3 borrow errors or panics and the captured temp-file contents are
  composed of whole message chunks. This is a smoke test for the public thread-
  safety contract, not a timing/GIL benchmark.

### 9.3 Integration tests (`tests/integration/`)

These need a real Linux machine with virmidi loaded. Skip if not present.

`tests/integration/conftest.py`:

```python
from __future__ import annotations
import shutil

import pytest

def virmidi_present() -> bool:
    try:
        with open("/proc/asound/cards") as f:
            return "VirMIDI" in f.read()
    except FileNotFoundError:
        return False

pytestmark = pytest.mark.skipif(
    not virmidi_present() or shutil.which("aconnect") is None,
    reason="needs snd-virmidi (`sudo modprobe snd-virmidi`) and aconnect (alsa-utils)",
)
```

(`conftest.py` also hosts the port-wiring fixture described below, using
`subprocess` to run `aconnect`.)

`tests/integration/test_roundtrip.py`:

**Verified mechanism** (tested on a target Raspberry Pi, 2026-06-11):
VirMIDI raw writes do **not** loop back to the same device's read side —
they are dispatched out the device's sequencer port only. Writing
`/dev/snd/midiC10D0` and reading `/dev/snd/midiC10D0` yields nothing;
wiring VirMIDI port 0 → port 1 with `aconnect` and reading
`/dev/snd/midiC10D1` returns the written bytes exactly. The round-trip
therefore uses **two** VirMIDI devices wired together through the sequencer:

1. Resolve the VirMIDI card number via `minimidi.find_card()` /
   `list_cards()` (skip if no VirMIDI card id is present).
2. Parse `aconnect -l` for the sequencer clients named
   `Virtual Raw MIDI <card>-0` and `Virtual Raw MIDI <card>-1`.
3. Fixture setup: `aconnect <clientA>:0 <clientB>:0`; teardown:
   `aconnect -d <clientA>:0 <clientB>:0`.
4. Open a reader on `/dev/snd/midiC<N>D1` with `O_RDONLY | O_NONBLOCK` and
   drain stale bytes before each test (the host may have pre-existing
   subscriptions feeding the port — the Pi does).
5. Construct `RawMidiOut(card_id, device=0)`; for each message type
   (`note_on`, `note_off`, `cc`, `send_bytes`) write known bytes, then read
   from the D1 fd via `select` with a 2-second deadline and assert exact
   byte equality.

`aconnect` (alsa-utils) is required at test time, but only to *wire* the
ports — no MIDI event text is ever parsed, so the brittleness of an
`aseqdump`-based approach is avoided. The conftest skips (never fails) when
`snd-virmidi` or `aconnect` is missing.

### 9.4 Stub correctness (`tests/test_stubs.py`)

Generate a tiny example script that exercises every public method and import style, then run `mypy --strict` against it. Failures here mean stubs drifted from implementation. Add a separate negative stub check proving the test-only `_open_path` hook is not visible in the typed public API.

```python
EXAMPLE = """
import minimidi
from minimidi import MinimidiError, RawMidiOut, find_card, list_cards

port: minimidi.RawMidiOut = RawMidiOut("VirMIDI1", device=0)
port.note_on(channel=16, note=60, velocity=100)
port.note_off(channel=16, note=60)
port.cc(channel=16, controller=74, value=64)
port.send_bytes(bytes([0xE0, 0, 64]))
port.close()
cards: list[tuple[int, str]] = list_cards()
n: int = find_card("VirMIDI1")
err_type: type[Exception] = MinimidiError
public: list[str] = minimidi.__all__
"""

NEGATIVE_EXAMPLE = """
from minimidi import RawMidiOut
RawMidiOut._open_path("/tmp/fake")
"""

def test_stubs_pass_mypy_strict(tmp_path):
    script = tmp_path / "example.py"
    script.write_text(EXAMPLE)
    result = subprocess.run(
        ["mypy", "--strict", str(script)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_test_hook_absent_from_public_stubs(tmp_path):
    script = tmp_path / "negative.py"
    script.write_text(NEGATIVE_EXAMPLE)
    result = subprocess.run(
        ["mypy", "--strict", str(script)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "_open_path" in result.stdout + result.stderr
```

---

## 10. CI / release

### 10.1 `ci.yml` — runs on every PR + push to main

```yaml
name: CI
on: { push: { branches: [main] }, pull_request: {} }

jobs:
  rust:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with: { components: clippy, rustfmt }
      - run: cargo fmt --check
      - run: cargo clippy --all-targets -- -D warnings
      - run: cargo test --release

  python:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.13", "3.14", "3.15-dev"]
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: astral-sh/setup-uv@v3
      - run: uv python install ${{ matrix.python-version }}
      - run: uv sync --all-groups --python ${{ matrix.python-version }}
      - run: uv run maturin develop --release
      - run: uv run ruff check
      - run: uv run mypy
      - run: uv run pytest tests -x

  integration:
    runs-on: ubuntu-latest
    needs: python
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: astral-sh/setup-uv@v3
      - run: sudo apt-get update && sudo apt-get install -y alsa-utils
      - run: sudo modprobe snd-virmidi midi_devs=2
      - run: |
          uv sync --all-groups
          uv run maturin develop --release
          uv run pytest tests/integration -x
```

The matrix runs against 3.13 (stable), 3.14 (stable), 3.15-dev (alpha/beta). `actions/setup-python`'s `3.15-dev` channel picks up the latest pre-release, so we get advance warning if a future Python breaks PyO3 abi3.

### 10.2 `release.yml` — runs on `v*` tag push

```yaml
name: Release
on:
  push: { tags: ["v*"] }

jobs:
  build:
    strategy:
      matrix:
        include:
          - { runner: ubuntu-latest, target: x86_64-unknown-linux-gnu }
          - { runner: ubuntu-latest, target: aarch64-unknown-linux-gnu }
    runs-on: ${{ matrix.runner }}
    steps:
      - uses: actions/checkout@v4
      - uses: PyO3/maturin-action@v1
        with:
          target: ${{ matrix.target }}
          manylinux: 2_28
          args: --release --out dist --features pyo3/abi3-py313
      - uses: actions/upload-artifact@v4
        with:
          name: wheels-${{ matrix.target }}
          path: dist/*.whl

  publish:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write       # PyPI trusted publishing (OIDC)
    steps:
      - uses: actions/download-artifact@v4
        with: { path: dist, pattern: "wheels-*", merge-multiple: true }
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Trusted publishing means no API tokens. The release workflow only runs against tags pushed by a maintainer with permission. Configure PyPI trusted publisher settings once after the first manual upload of v0.1.0.

### 10.3 Version + tag flow

1. Bump `version` in `Cargo.toml`, `pyproject.toml`, `python/minimidi/__init__.py`.
2. Update `CHANGELOG.md` with the new version section.
3. Commit, tag `v0.1.0`, push.
4. CI builds wheels for both Linux targets, publishes to PyPI.

A small `scripts/release.sh` (committed) automates step 1 with a single argument; included for ergonomics, not required for the workflow.

---

## 11. Documentation & community

### 11.1 `README.md`

The single source of usage docs for v1.0. Sections:

1. **Status banner** — Linux only, write-only, Python ≥3.13.
2. **What it is + what it isn't** — abbreviated §1 and §2.
3. **Install** — `uv add minimidi` or `pip install minimidi`.
4. **Quick start** — 10-line example.
5. **API reference** — link to the stub file (it's self-documenting).
6. **VirMIDI cookbook** — how to set up `snd-virmidi` for testing.
7. **Troubleshooting** — common errors (card not found, permission denied).
8. **Contributing** — link to `CONTRIBUTING.md`.
9. **License** — MIT.

### 11.2 `CONTRIBUTING.md`

- How to run tests locally.
- The "no scope creep" rule: PRs that add features beyond §2's "in scope" list will be closed unless they're additive (e.g. a new message type method) and don't change the existing surface.
- Sign-off: DCO (no CLA).

### 11.3 `CHANGELOG.md`

Keep-a-Changelog format. Every release annotated with breaking / added / fixed sections.

### 11.4 No Sphinx, no Read-the-Docs, no docs site for v1.0

The library is small enough that the README + stubs + docstrings are sufficient. If it grows past v1.0, revisit.

---

## 12. Integration with the downstream consumer

Once `minimidi` v0.1.0 is on PyPI, the consumer-side changes are tiny:

### 12.1 `webapp/pyproject.toml`

```toml
dependencies = [
  "starlette>=0.40",
  "uvicorn[standard]>=0.30",
  "python-osc>=1.8",
  "minimidi>=0.1.0",          # <-- replaces python-rtmidi
  "aiofiles>=24.1",
  "pydantic>=2.0",
  "pydantic-settings>=2.0",
]
```

### 12.2 `webapp/midi_bridge.py`

Replace `import rtmidi` with `import minimidi`. The MidiBridge API stays the same; only the internals change:

```python
import minimidi

class MidiBridge:
    def __init__(self, port_config: dict[tuple[int, str], tuple[str, int]]) -> None:
        # port_config maps (player, role) -> (card_id, device)
        # e.g. (1, "lp_a") -> ("VirMIDI1", 0)
        self._port_config = port_config
        self._ports: dict[tuple[int, str], minimidi.RawMidiOut] = {}
        self._available: dict[tuple[int, str], bool] = {}

    def open(self) -> None:
        for key, (card_id, device) in self._port_config.items():
            try:
                self._ports[key] = minimidi.RawMidiOut(card_id, device)
                self._available[key] = True
            except (minimidi.MinimidiError, OSError) as exc:
                logger.error("Failed to open %s:%d: %s", card_id, device, exc)
                self._available[key] = False

    def send(self, data: dict, player: int) -> None:
        msg_type = data.get("type")
        # Routing logic unchanged from the previous design;
        # only the per-port .send_message() becomes .note_on()/.cc()/etc.
        ...
```

### 12.3 `webapp/lc_mapping.py`

Drop `knob_to_midi`, `fader_to_midi`, `button_to_midi` helpers that returned raw byte lists. Replace with direct calls into `minimidi.RawMidiOut.note_on()` / `.cc()` from the bridge.

### 12.4 V8 verification

The consumer's bootstrap verification becomes:

```bash
test -x $CONSUMER_REPO/webapp/.venv/bin/python && \
  $CONSUMER_REPO/webapp/.venv/bin/python -c \
  'import starlette, uvicorn, pythonosc, minimidi'
```

(`rtmidi` removed; `minimidi` added.)

### 12.5 V5 / bootstrap

Unchanged — `minimidi` doesn't need any system packages. The Pi already has `snd-virmidi` and `/dev/snd/midi*` device files; `minimidi` opens them directly.

### 12.6 Cutover sequencing

| When | What |
|---|---|
| `minimidi` Phase 0–2 complete (v0.1.0 on PyPI) | The consumer can adopt it from the start; no transition needed. |
| If the consumer's work starts before `minimidi` is published | It pins `minimidi @ git+https://github.com/<owner>/minimidi@<sha>` until v0.1.0 lands, then switches to the version pin. |

---

## 13. Phased delivery

### Phase 0 — Repo + skeleton + first wheel (target: 1 session)

- Create GitHub repo.
- Land the file layout from §7.
- `Cargo.toml`, `pyproject.toml`, minimal `src/lib.rs` with just `RawMidiOut::new` + `close`.
- `uv sync` + `maturin develop --release` produces a working `.so` on the dev machine.
- README placeholder.

**Exit criteria:** `uv run python -c "import minimidi; print(minimidi)"` succeeds in the dev venv.

### Phase 1 — Public API + tests + stubs (target: 1–2 sessions)

- Implement `note_on`, `note_off`, `cc`, `send_bytes`, validation.
- `list_cards`, `find_card`.
- Context manager.
- Hand-write `.pyi` stubs.
- Rust unit tests (`cargo test`).
- Python unit tests with mocked write fixtures.
- Integration test file with virmidi guard.
- `ruff` + `mypy --strict` clean.

**Exit criteria:** all of §9's tests pass; `mypy --strict` is clean against a consumer example script.

### Phase 2 — CI + cibuildwheel + first PyPI release (target: 1 session)

- Land `ci.yml` and `release.yml`.
- Configure PyPI trusted publishing.
- Cut tag `v0.1.0`; CI publishes wheels for x86_64 and aarch64 manylinux.
- README finalised; `CHANGELOG.md` populated.

**Exit criteria:** `pip install minimidi` works on a fresh aarch64 Linux machine and the quick-start example runs.

### Phase 3 — downstream consumer cutover (target: 1 session)

- Replace `python-rtmidi` in `webapp/pyproject.toml`.
- Update `webapp/midi_bridge.py` (§12.2).
- Update `lc_mapping.py` (§12.3).
- Update the consumer's bootstrap verification command (§12.4).
- Smoke test on the Pi.

**Exit criteria:** the consumer webapp's acceptance checklist passes with `minimidi` substituted for `rtmidi`.

### Phase 4 — Docs polish + v1.0 freeze (target: 1 session, after Phase 3 stable)

- Expand README with troubleshooting section.
- Add `CONTRIBUTING.md`.
- Tag `v1.0.0`; declare the API stable.

**Exit criteria:** v1.0.0 published; README has soaked through a real production deployment without bug reports for ≥1 month.

---

## 14. Open questions

| # | Question | Resolution path |
|---|---|---|
| Q1 | Repository host + organisation | Default: maintainer's GitHub account. Confirm before Phase 0. |
| Q2 | License: MIT, Apache-2.0, or dual? | Default: MIT (simplest). Reconsider if downstream wants Apache patent grant. |
| Q3 | Is `minimidi` the right PyPI name, or is it taken? | Check `pip index versions minimidi` before Phase 0. Fallback: `pyminimidi` or `minimidi-rs`. |
| Q4 | macOS / Windows support story | v1.0 = Linux only with clean import-time error. Cross-platform = post-1.0 if anyone asks. |
| Q5 | Should `send_bytes` support iterables / `bytearray` / `memoryview`? | **Decided (2026-06-11):** v0.1 = `bytes` only, enforced via explicit `isinstance` check in `send_bytes` that raises `TypeError` on anything else (§5.1). Relaxing later is non-breaking. |
| Q6 | Async API (`AsyncRawMidiOut`)? | Out of v1.0. Wrap with `asyncio.to_thread` at the call site. |
| Q7 | Pre-1.0 stability promise? | Pre-1.0 = breaking changes only at minor-version bumps (0.x → 0.y), documented in CHANGELOG. After 1.0, semver. |

---

## 15. Cross-references

- PyO3 docs: <https://pyo3.rs/>
- Maturin docs: <https://www.maturin.rs/>
- `uv` docs: <https://docs.astral.sh/uv/>
- `cibuildwheel` docs: <https://cibuildwheel.pypa.io/>
- ALSA Raw MIDI: <https://www.alsa-project.org/alsa-doc/alsa-lib/group___raw_midi.html>
- Linux source: `sound/drivers/virmidi.c`, `sound/core/rawmidi.c`.
