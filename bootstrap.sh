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

run_playbook() {
  if [ -f "$REPO_ROOT/playbooks/site.yml" ]; then
    log "running provision playbook (playbooks/site.yml)"
    # homebrew_path="" keeps the brew modules on PATH lookup: in tests that is
    # the stub dir; here, /opt/homebrew/bin after `eval "$(brew shellenv)"` above.
    # (Omitting it makes them prefer hardcoded /usr/local:/opt/homebrew dirs.)
    (cd "$REPO_ROOT" && ansible-playbook -i playbooks/hosts \
      -e 'homebrew_path=""' playbooks/site.yml)
  else
    log "playbooks/site.yml not present yet: skipping (lands in a later milestone)"
  fi

  # The agents VM playbook is the opt-in second half (the choice was made in
  # choose_agents_vm; a "yes" without the secrets file already failed this run in
  # main, so nothing is half-installed). It installs or updates OrbStack itself —
  # the Mac baseline no longer carries it.
  if [ "${AGENTS_VM_CHOICE:-false}" != true ]; then
    return 0
  fi
  if [ ! -f "$REPO_ROOT/playbooks/agents-vm.yml" ]; then
    log "playbooks/agents-vm.yml not present yet: skipping (lands in a later milestone)"
    return 0
  fi
  # The array is never empty (the vault-password argument is always present), which
  # keeps bash 3.2 + set -u happy — expanding an empty array would be fatal there.
  local extra_args=(--ask-vault-pass)   # no AGENTS_VAULT_PASSWORD_FILE: ask, don't fail
  if [ -n "${AGENTS_VAULT_PASSWORD_FILE:-}" ]; then
    extra_args=(--vault-password-file "$AGENTS_VAULT_PASSWORD_FILE")
  fi
  if [ -n "${AGENTS_VAULT_SECRETS_FILE:-}" ]; then   # non-default location (tests)
    extra_args+=(-e "agents_vm_secrets_file=$AGENTS_VAULT_SECRETS_FILE")
  fi
  log "running agents VM playbook (playbooks/agents-vm.yml)"
  (cd "$REPO_ROOT" && ansible-playbook -i playbooks/hosts "${extra_args[@]}" \
    playbooks/agents-vm.yml)
}

# The agents VM (and with it OrbStack, which the playbook now installs itself) is
# opt-in and needs secrets: ask on every interactive run — the question covers an
# update, so it is asked even when a VM already exists (default No) — and let
# automation pre-answer with PROVISION_AGENTS_VM=1/true|0/false (invalid values
# fail before anything runs). No terminal attached: No, never hang. On "yes", main
# then checks the secrets file exists (require_agents_vm_secrets) BEFORE any install
# work; AGENTS_VAULT_PASSWORD_FILE points at the vault password file, and without it
# ansible is asked interactively. AGENTS_VAULT_SECRETS_FILE names a non-default
# secrets file (kept for tests; the playbook's own check is the backstop).
choose_agents_vm() {
  AGENTS_VM_CHOICE=false
  case "${PROVISION_AGENTS_VM:-}" in
    "" ) : ;;   # no pre-answer: ask below (or default No when nobody can be asked)
    1|true ) AGENTS_VM_CHOICE=true; log "agents VM: provisioning (PROVISION_AGENTS_VM pre-answered yes)"; return 0 ;;
    0|false ) log "agents VM: skipping (PROVISION_AGENTS_VM pre-answered no; OrbStack and the VM left as they are)"; return 0 ;;
    * ) log "error: PROVISION_AGENTS_VM must be 1/true or 0/false (got '${PROVISION_AGENTS_VM}')" >&2; return 1 ;;
  esac

  if [ ! -t 0 ]; then
    log "agents VM: no terminal attached — skipping (OrbStack and the VM left as they are; set PROVISION_AGENTS_VM=1 to opt in)"
    return 0
  fi

  local reply=""
  printf 'Install/update OrbStack and the agents VM (Hermes Agent + OpenCode)? [y/N] '
  IFS= read -r reply || true
  case "$reply" in
    y|Y ) AGENTS_VM_CHOICE=true; log "agents VM: provisioning (yes at the prompt)" ;;
    * ) AGENTS_VM_CHOICE=false; log "agents VM: skipping (OrbStack and the VM left as they are)" ;;
  esac
}

# A "yes" means installing/updating OrbStack and provisioning the VM — both need the
# secrets file (the playbook's own pre-flight is the backstop for direct runs). Fail
# here, before any install work at all.
require_agents_vm_secrets() {
  local secrets="${AGENTS_VAULT_SECRETS_FILE:-$REPO_ROOT/playbooks/secrets/agents-vm-secrets.yml}"
  if [ ! -f "$secrets" ]; then
    log "error: agents VM secrets file not found: $secrets (nothing was installed)" >&2
    log "(copy playbooks/secrets/agents-vm-secrets.example.yml to that name, fill it in and encrypt" >&2
    log "it with ansible-vault — see README.md → Agents VM; then re-run)" >&2
    return 1
  fi
}

main() {
  choose_agents_vm                # first: ask, and fail fast on a bad pre-answer
  if [ "${AGENTS_VM_CHOICE:-false}" = true ]; then require_agents_vm_secrets; fi
  ensure_command_line_tools
  ensure_xcode_license
  ensure_homebrew
  add_brew_to_zprofile
  ensure_ansible
  run_playbook
  log "one-time follow-ups: sign in with 'claude' and 'codex login'; run /setup-matt-pocock-skills once in each repo"
  log "done"
}

main "$@"
