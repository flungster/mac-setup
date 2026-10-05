#!/usr/bin/env bash
# verify.sh - real-machine smoke checks after ./bootstrap.sh. It never installs;
# it reports what is missing and how to fix it, then exits non-zero on any gap.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
status=0
ok() { printf '[verify] ok: %s\n' "$*"; }
missing() { printf '[verify] missing: %s — fix with: %s\n' "$1" "$2"; status=1; }

# The agents VM's knobs (machine name, ports) live in playbooks/vars_agents_vm.yml —
# the playbook is the single source of truth, so verify must not hard-code copies.
# Those lines are plain scalars ("key: value  # comment"), so sed extraction suffices.
VARS_FILE="$REPO_ROOT/playbooks/vars_agents_vm.yml"
vm_var() { sed -n "s/^$1:[[:space:]]*\([^ #]*\).*/\1/p" "$VARS_FILE" | head -n 1; }
AGENTS_VM_NAME="" OPENCODE_PORT="" DASHBOARD_PORT=""
if [ -f "$VARS_FILE" ]; then
  AGENTS_VM_NAME="$(vm_var agents_vm_name)"
  OPENCODE_PORT="$(vm_var opencode_port)"
  DASHBOARD_PORT="$(vm_var hermes_dashboard_port)"
fi

for cmd in claude codex node; do
  if command -v "$cmd" >/dev/null 2>&1; then
    if version="$("$cmd" --version 2>/dev/null | head -n1)"; then
      ok "$cmd ($version)"
    else
      missing "$cmd (--version failed)" "re-run ./bootstrap.sh; if it still fails, reinstall the package and sign in again"
    fi
  else
    case "$cmd" in
      claude) missing "claude (Claude Code)" "brew install --cask claude-code, then sign in with: claude" ;;
      codex) missing "codex (Codex)" "brew install --cask codex, then sign in with: codex login" ;;
      node) missing "node (Node.js, needed by the skills CLI)" "brew install --formula node" ;;
    esac
  fi
done

# The agents VM (opt-in at the bootstrap question, or PROVISION_AGENTS_VM=1) is only
# checked when OrbStack exists and the machine was created: declining it must not
# fail verify. Name/ports come from playbooks/vars_agents_vm.yml (above).
if [ -n "$AGENTS_VM_NAME" ] && command -v orb >/dev/null 2>&1 \
   && (orb list 2>/dev/null | grep -qw "$AGENTS_VM_NAME"); then
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "$AGENTS_VM_NAME@orb" true >/dev/null 2>&1; then
    ok "agents VM reachable via ssh $AGENTS_VM_NAME@orb"
  else
    missing "agents VM (ssh $AGENTS_VM_NAME@orb)" \
      "./bootstrap.sh and answer yes to the agents VM question (or PROVISION_AGENTS_VM=1), or start the machine: orb start $AGENTS_VM_NAME"
  fi

  dashboard_status="$(curl -s --max-time 5 "http://127.0.0.1:$DASHBOARD_PORT/api/status" 2>/dev/null || true)"
  if printf '%s' "$dashboard_status" | grep -q '"basic"' && \
     printf '%s' "$dashboard_status" | grep -Eq '"auth_required"[[:space:]]*:[[:space:]]*true'; then
    ok "Hermes dashboard auth gate is on (http://127.0.0.1:$DASHBOARD_PORT, provider basic)"
  else
    missing "Hermes dashboard (http://<mac-ip>:$DASHBOARD_PORT, should prompt for a login)" \
      "on the VM: sudo systemctl restart hermes-dashboard; check ~/.hermes/.env has HERMES_DASHBOARD_BASIC_AUTH_*"
  fi

  if curl -s -o /dev/null --max-time 5 "http://127.0.0.1:$OPENCODE_PORT"; then
    ok "OpenCode server is up (http://127.0.0.1:$OPENCODE_PORT, VM-local)"
  else
    missing "OpenCode server (http://127.0.0.1:$OPENCODE_PORT)" \
      "on the VM: sudo systemctl restart opencode-server"
  fi
fi

agents_skills="$HOME/.agents/skills"
claude_skills="$HOME/.claude/skills"

for marker in \
  "$agents_skills/setup-matt-pocock-skills/SKILL.md" \
  "$claude_skills/setup-matt-pocock-skills/SKILL.md"; do
  if [ -f "$marker" ]; then
    ok "skill marker: $marker"
  else
    missing "Matt Pocock skills ($marker)" "./bootstrap.sh (re-running is the install/update path)"
  fi
done

if [ -d "$agents_skills" ] && [ -d "$claude_skills" ]; then
  if diff \
    <(cd "$agents_skills" && find . -mindepth 1 -maxdepth 1 | sort) \
    <(cd "$claude_skills" && find . -mindepth 1 -maxdepth 1 | sort) >/dev/null; then
    ok "Claude Code's skill symlinks match the shared .agents set"
  else
    missing "Claude Code / OpenCode-Codex skill sets differ" \
      "./bootstrap.sh, or: npx -y skills@latest add mattpocock/skills --global --skill '*' --agent codex --agent claude-code --yes"
  fi
fi

if [ "$status" -ne 0 ]; then
  printf '[verify] failed: see missing items above\n' >&2
  exit 1
fi

printf '[verify] passed: Claude Code, Codex and Node.js are present; Matt Pocock skills are available to OpenCode/Codex via ~/.agents/skills and to Claude Code via ~/.claude/skills\n'
