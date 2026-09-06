#!/usr/bin/env bash
# Shared state helpers for the CLI stubs in this directory (brew, xcode-select,
# xcodebuild, xcodes). Each stub sets STUB_TOOL before sourcing this file.

if [ -z "${STUB_STATE_DIR:-}" ]; then
  echo "stub: STUB_STATE_DIR environment variable is required" >&2
  exit 64
fi

STUB_STATE_FILE="$STUB_STATE_DIR/state.env"
STUB_LOG_FILE="$STUB_STATE_DIR/invocations.log"

mkdir -p "$STUB_STATE_DIR"
touch "$STUB_LOG_FILE" "$STUB_STATE_FILE"

# stub_log <args...> - record one invocation as "<tool> args..."
stub_log() {
  printf '%s\n' "${STUB_TOOL} $*" >>"$STUB_LOG_FILE"
}

# stub_get <key> - print the value stored for key (empty if unset)
stub_get() {
  local key="$1" k v value=""
  while IFS='=' read -r k v; do
    if [ "$k" = "$key" ]; then value="$v"; fi
  done <"$STUB_STATE_FILE"
  printf '%s' "$value"
}

# stub_set <key> <value> - store value for key; empty value deletes the key
stub_set() {
  local key="$1" val="${2:-}" k v tmp
  tmp="$(mktemp "${STUB_STATE_FILE}.XXXXXX")" || return 1
  while IFS='=' read -r k v; do
    if [ "$k" != "$key" ]; then printf '%s=%s\n' "$k" "$v" >>"$tmp"; fi
  done <"$STUB_STATE_FILE"
  if [ -n "$val" ]; then printf '%s=%s\n' "$key" "$val" >>"$tmp"; fi
  mv "$tmp" "$STUB_STATE_FILE" || return 1
}
