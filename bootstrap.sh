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

ensure_xcode_license() {
  # Full Xcode (unlike CLT) gates xcrun-served tools and `brew install` behind
  # a license. A fresh Xcode install — or an update, which resets acceptance —
  # leaves it unaccepted until sudo-accepted; CLT has no such gate. This script
  # is human-driven, so prompt for the password in place (like the CLT dialog).
  local devdir
  devdir="$(xcode-select -p)" || return 0
  case "$devdir" in
    /Library/Developer/*) log "CLT active: no Xcode license gate"; return 0 ;;
  esac
  if xcodebuild -license status >/dev/null 2>&1; then
    log "Xcode license: accepted"
    return 0
  fi
  log "Xcode license not accepted: running 'sudo xcodebuild -license accept' (may prompt for a password)"
  sudo xcodebuild -license accept
}

ensure_homebrew() {
  local brew="$HOMEBREW_PREFIX/bin/brew"
  if [ ! -x "$brew" ]; then
    # Deliberately NOT NONINTERACTIVE=1: in that mode the official installer checks
    # sudo with `sudo -n` (no password prompt), which fails on a fresh Mac where the
    # session has no cached sudo credentials — even for an administrator. Interactive,
    # the installer asks for the password in place (like every other step here).
    log "Homebrew not found at $HOMEBREW_PREFIX: installing from official script (will ask for your password)"
    /bin/bash -c "$(curl -fsSL "$BREW_INSTALL_URL")"
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
    # homebrew_path="" keeps the brew modules on PATH lookup: in tests that is
    # the stub dir; here, /opt/homebrew/bin after `eval "$(brew shellenv)"` above.
    # (Omitting it makes them prefer hardcoded /usr/local:/opt/homebrew dirs.)
    (cd "$REPO_ROOT" && ansible-playbook -i playbooks/hosts -e 'homebrew_path=""' playbooks/site.yml)
  else
    log "playbooks/site.yml not present yet: skipping (lands in a later milestone)"
  fi
}

main() {
  ensure_command_line_tools
  ensure_xcode_license
  ensure_homebrew
  ensure_ansible
  run_playbook
  log "done"
}

main "$@"
