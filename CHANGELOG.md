# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-1.0: breaking changes only at minor-version bumps).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-06-11

### Added

- Initial public API: `RawMidiOut` with `note_on()`, `note_off()`,
  `cc()`, `send_bytes()`, `close()`, context-manager support, and `card_id` /
  `device` / `is_open` properties.
- Card lookup helpers: `list_cards()` and `find_card()`. A host without
  ALSA (no `/proc/asound/cards`) behaves like a host with zero cards.
- `MinimidiError` exception type; OS-level failures propagate as the
  standard errno-derived built-ins (`FileNotFoundError`, `PermissionError`,
  `BrokenPipeError`, ...).
- PEP 561 typing: `py.typed` marker and hand-written `_minimidi.pyi` stubs;
  clean under `mypy --strict`.
- Prebuilt `abi3` wheels (Python ≥3.13) for x86_64 and aarch64 manylinux.

[Unreleased]: https://github.com/ModularDevicesMalleableAudio/minimidi/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ModularDevicesMalleableAudio/minimidi/releases/tag/v0.1.0
