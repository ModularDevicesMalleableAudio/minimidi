# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-1.0: breaking changes only at minor-version bumps).

## [Unreleased]

### Added

- Initial public API: `RawMidiOut` with `note_on()`, `note_off()`,
  `cc()`, `send_bytes()`, `close()`, context-manager support, and `card_id` /
  `device` / `is_open` properties.
- Card lookup helpers: `list_cards()` and `find_card()`.
- `MinimidiError` exception type.
- PEP 561 typing: `py.typed` marker and hand-written `_minimidi.pyi` stubs.
