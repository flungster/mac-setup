#!/usr/bin/env bash
# Static checks for all shell files in the repo (bootstrap, scripts, stubs).
set -euo pipefail

cd "$(dirname "$0")/.."

files=()
for f in bootstrap.sh scripts/*.sh tests/stubs/*; do
  if [ -f "$f" ]; then files+=("$f"); fi
done

if [ "${#files[@]}" -eq 0 ]; then
  echo "error: no shell files found to check" >&2
  exit 1
fi

for f in "${files[@]}"; do bash -n "$f"; done
echo "bash syntax ok: ${#files[@]} file(s)"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${files[@]}"
  echo "shellcheck ok"
else
  echo "shellcheck not installed - skipped (brew install shellcheck / apt-get install shellcheck)"
fi
