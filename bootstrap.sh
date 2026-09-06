#!/usr/bin/env bash
# bootstrap.sh - one entry point for a fresh (or existing) Mac.
# Ensures Homebrew, Command Line Tools and Ansible are present/current, then
# runs the provision playbook. Safe to re-run: it is also the update path.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export REPO_ROOT

log() { printf '[bootstrap] %s\n' "$*" >&2; }

# Homebrew location: honor HOMEBREW_PREFIX (real Homebrew semantics), else
# default by architecture. Both are overridable for tests via the environment.
if [ -z "${HOMEBREW_PREFIX:-}" ]; then
  if [[ "$(uname -m)" == "arm64" ]]; then
    HOMEBREW_PREFIX="/opt/homebrew"
  else
    HOMEBREW_PREFIX="/usr/local"
  fi
fi

BREW_INSTALL_URL="${BREW_INSTALL_URL:-https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh}"
export BREW_INSTALL_URL

ensure_command_line_tools() {
  if xcode-select -p >/dev/null 2>&1; then
    log "Command Line Tools: present ($(xcode-select -p))"
  else
    log "Command Line Tools missing: requesting install (a system dialog may appear)"
    xcode-select --install
  fi
}

ensure_homebrew() {
  local brew="$HOMEBREW_PREFIX/bin/brew"
  if [ ! -x "$brew" ]; then
    log "Homebrew not found at $HOMEBREW_PREFIX: installing from official script (non-interactive)"
    NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL "$BREW_INSTALL_URL")"
  else
    log "Homebrew found: $("$brew" --version | head -n1)"
  fi
  eval "$("$HOMEBREW_PREFIX/bin/brew" shellenv)"
}

ensure_ansible() {
  local brew="$HOMEBREW_PREFIX/bin/brew"
  if "$brew" list --formula ansible >/dev/null 2>&1; then
    log "ansible: already installed via Homebrew"
  else
    log "installing ansible via Homebrew"
    "$brew" install --formula ansible
  fi
}

run_playbook() {
  if [ -f "$REPO_ROOT/playbooks/site.yml" ]; then
    log "running provision playbook (playbooks/site.yml)"
    (cd "$REPO_ROOT" && ansible-playbook -i playbooks/hosts playbooks/site.yml)
  else
    log "playbooks/site.yml not present yet: skipping (lands in a later milestone)"
  fi
}

main() {
  ensure_command_line_tools
  ensure_homebrew
  ensure_ansible
  run_playbook
  log "done"
}

main "$@"
