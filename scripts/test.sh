#!/usr/bin/env bash
# Run the full test suite: Rust unit tests + Python tests.
#
# Usage:
#   scripts/test.sh                 # default venv (Python from .python-version)
#   scripts/test.sh --no-build      # skip maturin rebuild
#   scripts/test.sh --python 3.14   # use a different Python via an isolated venv
#
# The Rust extension is built once into the chosen venv before pytest runs.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD=1
PYTHON=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-build)  BUILD=0; shift ;;
        --python)    PYTHON="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *)
            echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

UV_ARGS=()
if [[ -n "$PYTHON" ]]; then
    export UV_PROJECT_ENVIRONMENT=".venv-py${PYTHON}"
    UV_ARGS+=(--python "$PYTHON")
    echo "==> using Python ${PYTHON} (venv: ${UV_PROJECT_ENVIRONMENT})"
fi

echo "==> cargo test"
cargo test

echo "==> uv sync"
uv sync --all-groups "${UV_ARGS[@]}"

if [[ "$BUILD" -eq 1 ]]; then
    echo "==> maturin develop --release"
    uv run "${UV_ARGS[@]}" maturin develop --release
fi

echo "==> ruff check"
uv run "${UV_ARGS[@]}" ruff check

echo "==> ruff format --check"
uv run "${UV_ARGS[@]}" ruff format --check

echo "==> mypy"
uv run "${UV_ARGS[@]}" mypy

echo "==> pytest"
uv run "${UV_ARGS[@]}" pytest tests

echo "==> all tests passed"
