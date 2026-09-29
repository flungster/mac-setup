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
    xcode-select --install || return 1
    # The install is user-driven (a dialog) and takes minutes. Wait for it to
    # finish: otherwise the Homebrew installer below sees missing CLT and starts
    # its own install in parallel. Intervals/timeout are env-overridable for tests.
    local wait_s="${CLT_WAIT_SECONDS:-1800}" poll_s="${CLT_POLL_INTERVAL:-5}" start=$SECONDS
    while ! xcode-select -p >/dev/null 2>&1; do
      if [ $((SECONDS - start)) -ge "$wait_s" ]; then
        log "error: Command Line Tools install did not finish within ${wait_s}s"
        log "(finish the dialog, or install from Software Update > General; then re-run ./bootstrap.sh)"
        return 1
      fi
      log "waiting for Command Line Tools install to complete..."
      sleep "$poll_s"
    done
    log "Command Line Tools: installed ($(xcode-select -p))"
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
  if xcodebuild -license check >/dev/null 2>&1; then
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
    # Download to a file, then run it: `bash -c "$(curl ...)"` would run an empty
    # script and exit 0 if the download failed, so a bad network looked like success.
    local installer_tmp
    if ! installer_tmp="$(mktemp)"; then log "error: mktemp failed"; return 1; fi
    if ! curl -fsSL "$BREW_INSTALL_URL" -o "$installer_tmp"; then
      rm -f "$installer_tmp"
      log "error: could not download Homebrew installer from $BREW_INSTALL_URL (check your network)"
      return 1
    fi
    if ! /bin/bash "$installer_tmp"; then
      rm -f "$installer_tmp"
      log "error: Homebrew installer failed (see output above)"
      return 1
    fi
    rm -f "$installer_tmp"
  else
    log "Homebrew found: $("$brew" --version | head -n1)"
  fi
  eval "$("$HOMEBREW_PREFIX/bin/brew" shellenv)"
}

# New terminals only know about brew if the shell env is loaded at login. The
# official installer suggests this snippet; we add it (idempotently) so a fresh
# Mac is done after one run. Skipped when an equivalent line already exists —
# e.g. added by the Homebrew installer or a previous run of this script.
add_brew_to_zprofile() {
  local zprofile="$HOME/.zprofile" marker="# Added by mac-setup bootstrap (brew shellenv)"
  local line="eval \"\$($HOMEBREW_PREFIX/bin/brew shellenv)\""
  if [ -f "$zprofile" ] && grep -Fqx -- "$line" "$zprofile"; then
    log "$zprofile already sources brew shellenv: leaving it alone"
  else
    printf '\n%s\n%s\n' "$marker" "$line" >>"$zprofile"
    log "added brew shellenv to $zprofile (new terminals will find brew)"
  fi
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

# Hermes Agent (Nous Research) is the one optional app. The choice is made here and
# passed to the playbook as -e install_hermes_agent=... INSTALL_HERMES_AGENT=1/0
# answers for the user (automation, tests); a re-run where Hermes is already present
# keeps managing it without asking again; with no TTY on stdin there is nobody to ask,
# so the answer stays off (never hang waiting for input).
choose_hermes() {
  local decided=false reply=""
  HERMES_CHOICE=false
  HERMES_FRESH=false
  case "${INSTALL_HERMES_AGENT:-}" in
    "" ) ;; # ask below (or default to off when nobody can be asked)
    1|true|yes ) HERMES_CHOICE=true; log "Hermes Agent: installing (INSTALL_HERMES_AGENT set)"; decided=true ;;
    0|false|no ) log "Hermes Agent: skipping (INSTALL_HERMES_AGENT set)"; decided=true ;;
    * ) log "error: INSTALL_HERMES_AGENT must be 1/true or 0/false (got '${INSTALL_HERMES_AGENT}')" >&2; return 1 ;;
  esac
  if [ "$decided" = false ] && [ -d "${HERMES_HOME:-$HOME/.hermes}/hermes-agent" ]; then
    HERMES_CHOICE=true  # already present: keep managing it (ADR-0001), don't re-prompt
    decided=true
  fi
  if [ "$decided" = false ] && [ -t 0 ]; then
    printf 'Install Hermes Agent? (optional, https://hermes-agent.nousresearch.com) [y/N] '
    IFS= read -r reply || true
    case "$reply" in
      y|Y|yes|YES ) HERMES_CHOICE=true ;;
      * ) log "Hermes Agent: skipping" ;;
    esac
  fi
  if [ "$decided" = false ]; then
    log "Hermes Agent: not installing (no prompt available; set INSTALL_HERMES_AGENT=1 to install)"
  fi
  if [ "$HERMES_CHOICE" = true ] && [ ! -d "${HERMES_HOME:-$HOME/.hermes}/hermes-agent" ]; then
    HERMES_FRESH=true  # a fresh install needs one-time configuration afterwards
  fi
}

run_playbook() {
  if [ -f "$REPO_ROOT/playbooks/site.yml" ]; then
    log "running provision playbook (playbooks/site.yml)"
    # homebrew_path="" keeps the brew modules on PATH lookup: in tests that is
    # the stub dir; here, /opt/homebrew/bin after `eval "$(brew shellenv)"` above.
    # (Omitting it makes them prefer hardcoded /usr/local:/opt/homebrew dirs.)
    # install_hermes_agent carries the user's opt-in for the optional Hermes Agent.
    (cd "$REPO_ROOT" && ansible-playbook -i playbooks/hosts \
      -e 'homebrew_path=""' -e "install_hermes_agent=${HERMES_CHOICE}" playbooks/site.yml)
  else
    log "playbooks/site.yml not present yet: skipping (lands in a later milestone)"
  fi
}

main() {
  choose_hermes  # first: the only stdin prompt — everything after is passwords and dialogs
  ensure_command_line_tools
  ensure_xcode_license
  ensure_homebrew
  add_brew_to_zprofile
  ensure_ansible
  run_playbook
  log "one-time follow-ups: sign in with 'claude' and 'codex login'; run /setup-matt-pocock-skills once in each repo"
  if [ "$HERMES_FRESH" = true ]; then
    log "one-time follow-up: run 'hermes model' (or the full wizard with 'hermes setup') to point Hermes at a provider"
  fi
  log "done"
}

main "$@"
