#!/usr/bin/env bash
# Stub gh (GitHub CLI) for offline playbook tests. Implements the auth flow the
# github_access role uses: `auth status` (state-driven), `auth login --with-token`
# (reads the token from stdin like the real CLI) and `auth setup-git`.
#
# Deliberately not named "gh" (and so not on PATH by itself): a file at
# tests/stubs/gh would be found by site.yml's formula-presence check (command -v
# gh) in the M3 tests, classifying brew's `gh` formula as manually installed.
# The agents-VM tests (tests/test_m5_agents_vm.py) put a per-test shim on PATH
# that delegates here.

STUB_TOOL="gh"
# shellcheck source=tests/stubs/_stub_state.sh
source "$(dirname "$0")/_stub_state.sh"

cmd="${1:-}"
shift || true
if [ "$#" -gt 0 ]; then stub_log "$cmd $*"; else stub_log "$cmd"; fi

case "$cmd" in
  auth)
    sub="${1:-}"; shift || true
    case "$sub" in
      status)
        if [ "$(stub_get gh.logged_in)" = "1" ]; then
          printf 'Logged in to github.com as stub\n'
          exit 0
        fi
        printf 'You are not logged into any GitHub hosts.\n' >&2
        exit 1
        ;;

      login)
        if [ "$*" != "--with-token --hostname github.com" ]; then
          echo "stub gh: unhandled login invocation: $*" >&2
          exit 1
        fi
        cat >/dev/null   # consume the token from stdin (never echo it back)
        stub_set gh.logged_in 1
        printf 'Logged in to github.com as stub\n'
        exit 0
        ;;

      setup-git)
        [ "$(stub_get gh.logged_in)" = "1" ] || { echo "gh: not logged in" >&2; exit 1; }
        stub_set gh.setup_git "${SECONDS}"
        exit 0
        ;;

      *)
        echo "stub gh: unhandled auth subcommand: $sub" >&2; exit 1 ;;
    esac
    ;;

  *)
    echo "stub gh: unhandled invocation: $cmd" >&2
    exit 1
    ;;
esac
