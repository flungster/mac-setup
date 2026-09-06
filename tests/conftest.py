"""Shared helpers and fixtures for the stub-based playbook tests.

Run everything through `make test` (provisions .test-venv first).
"""
import os
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STUBS_DIR = REPO_ROOT / "tests" / "stubs"


def venv_bin() -> pathlib.Path:
    b = REPO_ROOT / ".test-venv" / "bin"
    if not (b / "ansible-playbook").exists():
        raise RuntimeError("test venv missing - run `make test` (or scripts/ensure_test_env.sh) first")
    return b


def seed_state(state_dir, casks=(), formulas=None, outdated_formulas=()):
    lines = []
    for c in casks:
        lines.append(f"cask.{c}=1")
    for name, version in (formulas or {}).items():
        lines.append(f"formula.{name}={version}")
    for name in outdated_formulas:
        lines.append(f"formula.{name}.outdated=1")
    (state_dir / "state.env").write_text("\n".join(lines) + ("\n" if lines else ""))


def run_playbook(playbook, state_dir, extra_vars=()):
    env = dict(os.environ)
    b = venv_bin()
    env["PATH"] = f"{STUBS_DIR}{os.pathsep}{b}{os.pathsep}{env.get('PATH', '')}"
    env["STUB_STATE_DIR"] = str(state_dir)
    env["ANSIBLE_PYTHON_INTERPRETER"] = str(b / "python")
    env["ANSIBLE_DEPRECATION_WARNINGS"] = "False"
    # homebrew_path="" disables the modules' hardcoded /usr/local:/opt/homebrew
    # search dirs (they take precedence over PATH), so the stubs in STUBS_DIR win.
    cmd = [str(b / "ansible-playbook"), "-i", "localhost,", str(playbook), "-e", 'homebrew_path=""']
    for v in extra_vars:
        cmd += ["-e", v]
    return subprocess.run(
        cmd, capture_output=True, text=True, env=env, cwd=str(REPO_ROOT), timeout=600
    )


def invocations(state_dir):
    log = state_dir / "invocations.log"
    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line]


def state_entries(state_dir):
    f = state_dir / "state.env"
    if not f.exists():
        return {}
    return dict(line.split("=", 1) for line in f.read_text().splitlines() if "=" in line)


@pytest.fixture()
def stub_state(tmp_path):
    d = tmp_path / "stub-state"
    d.mkdir()
    return d
