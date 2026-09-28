#!/usr/bin/env bash
# verify.sh - real-machine smoke checks after ./bootstrap.sh. It never installs;
# it reports what is missing and how to fix it, then exits non-zero on any gap.
set -euo pipefail

status=0
ok() { printf '[verify] ok: %s\n' "$*"; }
missing() { printf '[verify] missing: %s — fix with: %s\n' "$1" "$2"; status=1; }

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
