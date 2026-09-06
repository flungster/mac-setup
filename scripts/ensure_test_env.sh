#!/usr/bin/env bash
# Provisions the isolated test environment (.test-venv) used by `make test`.
set -euo pipefail

cd "$(dirname "$0")/.."

VENV_DIR=".test-venv"
REQ_FILE="requirements-test.txt"

pick_python() {
  local candidate
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(pick_python)" || { echo "error: Python >= 3.10 is required for the test venv" >&2; exit 1; }

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "creating test venv with $PYTHON_BIN ($("$PYTHON_BIN" --version))"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install -q --disable-pip-version-check -r "$REQ_FILE"
echo "test env ready: $VENV_DIR/bin/ansible-playbook (python $("$VENV_DIR/bin/python" --version 2>&1))"
