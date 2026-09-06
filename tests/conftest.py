"""Shared helpers and fixtures for the stub-based playbook tests.

Run everything through `make test` (provisions .test-venv first).
"""
import os
import pathlib
import shlex
import subprocess
from types import SimpleNamespace

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STUBS_DIR = REPO_ROOT / "tests" / "stubs"


def venv_bin() -> pathlib.Path:
    b = REPO_ROOT / ".test-venv" / "bin"
    if not (b / "ansible-playbook").exists():
        raise RuntimeError("test venv missing - run `make test` (or scripts/ensure_test_env.sh) first")
    return b


def seed_state(state_dir, casks=(), formulas=None, outdated_formulas=(), extra=None):
    lines = []
    for c in casks:
        lines.append(f"cask.{c}=1")
    for name, version in (formulas or {}).items():
        lines.append(f"formula.{name}={version}")
    for name in outdated_formulas:
        lines.append(f"formula.{name}.outdated=1")
    for key, value in (extra or {}).items():
        lines.append(f"{key}={value}")
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


@pytest.fixture()
def bootstrap(tmp_path):
    """Run ./bootstrap.sh against the stubs.

    Returns a namespace with: prefix (fake HOMEBREW_PREFIX), state_dir,
    install_brew() to simulate an already-installed Homebrew, and run().
    """
    prefix = tmp_path / "homebrew"
    state_dir = tmp_path / "stub-state"
    state_dir.mkdir()

    wrapper = prefix / "bin" / "brew"
    installer_text = "\n".join(
        [
            "#!/bin/sh",
            f"mkdir -p {shlex.quote(str(prefix / 'bin'))}",
            "printf '%s\\n' '#!/bin/sh' 'exec {0} \"$@\"'{1}".format(
                shlex.quote(str(STUBS_DIR / "brew")), f" > {shlex.quote(str(wrapper))}"
            ),
            f"chmod +x {shlex.quote(str(wrapper))}",
        ]
    )
    installer = tmp_path / "fake-brew-installer.sh"
    installer.write_text(installer_text + "\n")

    def install_brew():
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(str(STUBS_DIR / "brew"))} "$@"\n')
        wrapper.chmod(0o755)

    env = dict(os.environ)
    b = venv_bin()
    env["PATH"] = f"{STUBS_DIR}{os.pathsep}{b}{os.pathsep}{env.get('PATH', '')}"
    env["STUB_STATE_DIR"] = str(state_dir)
    env["HOMEBREW_PREFIX"] = str(prefix)
    env["FAKE_BREW_INSTALLER"] = str(installer)

    def run(extra_env=None):
        merged = dict(env)
        if extra_env:
            merged.update(extra_env)
        return subprocess.run(
            ["bash", str(REPO_ROOT / "bootstrap.sh")],
            capture_output=True, text=True, env=merged, cwd=str(REPO_ROOT), timeout=600,
        )

    return SimpleNamespace(
        prefix=prefix, state_dir=state_dir, env=env, install_brew=install_brew, run=run
    )
