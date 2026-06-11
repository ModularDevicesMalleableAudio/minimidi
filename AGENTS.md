# Agent Instructions

Mixed Rust + Python project.

## Toolchain
- Python: `uv` (reads `.python-version`, pins 3.13)
- Rust: `cargo` (stable) + `maturin` for PyO3 builds
- Build backend: `maturin` (mixed layout, Rust in `src/`, Python in `python/minimidi/`)

## Setup
```
uv sync --all-groups            # creates .venv, installs dev deps
uv run maturin develop --release  # builds Rust ext into the venv
```

## Tests
Run both Rust and Python suites:
```
./scripts/test.sh               # rebuilds ext, runs cargo test + pytest
./scripts/test.sh --no-build    # skip maturin rebuild (Rust-only changes still need it)
```

## File-Scoped Commands
| Task | Command |
|------|---------|
| Python test file | `uv run pytest tests/test_<name>.py` |
| Rust unit tests | `cargo test` |
| Rust lint | `cargo clippy -- -D warnings` |
| Rust format check | `cargo fmt --check` |
| Python lint | `uv run ruff check python/minimidi tests` |
| Python typecheck | `uv run mypy python/minimidi tests` |

After editing `src/lib.rs`, rerun `uv run maturin develop --release` before `pytest`.

## Layout
- `src/lib.rs` — Rust extension (PyO3, abi3-py313)
- `python/minimidi/` — Python wrapper + `.pyi` stubs + `py.typed`
- `tests/` — Python tests (unit + `tests/integration/` for VirMIDI-dependent)

## Conventions
- Docstrings: opening `"""` on its own line, content underneath, closing `"""` on its own line.
- All `.pyi` stubs are hand-written (single source of truth for static types).
- `mypy --strict` must stay clean.
- Integration tests under `tests/integration/` are skipped when `snd-virmidi` isn't loaded.

