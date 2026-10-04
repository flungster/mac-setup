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


def playbook_inventory():
    """(cask names, formula names) from playbooks/site.yml — the single source of truth.

    Tests must not carry their own copy of the inventory: adding an app there
    would silently desync from these lists. PyYAML ships with ansible-core.
    """
    import yaml

    with open(REPO_ROOT / "playbooks" / "site.yml", encoding="utf-8") as f:
        play = yaml.safe_load(f)[0]
    casks = [c["name"] for c in play["vars"]["casks"]]
    formulas = [(x if isinstance(x, str) else x["name"]) for x in play["vars"]["formulas"]]
    return casks, formulas


def playbook_bin_casks():
    """Command names for command-line-only casks (bin: entries) in playbooks/site.yml."""
    import yaml

    with open(REPO_ROOT / "playbooks" / "site.yml", encoding="utf-8") as f:
        play = yaml.safe_load(f)[0]
    return [c["bin"] for c in play["vars"]["casks"] if isinstance(c, dict) and "bin" in c]


MATT_SKILL_MARKER_RELPATHS = (
    ".agents/skills/setup-matt-pocock-skills/SKILL.md",
    ".claude/skills/setup-matt-pocock-skills/SKILL.md",
)
MATT_SKILLS_LOCK_RELPATH = ".agents/.skill-lock.json"


def seed_matt_skill_markers(home):
    """Create the Matt Pocock presence markers only (a manual/present install)."""
    home = pathlib.Path(home)
    for rel in MATT_SKILL_MARKER_RELPATHS:
        p = home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text(
                "---\nname: setup-matt-pocock-skills\ndescription: stub marker\n---\nstub skill\n",
                encoding="utf-8",
            )


def seed_managed_matt_skills(home):
    """Create the Matt Pocock markers plus an installer lock (a managed install)."""
    seed_matt_skill_markers(home)
    home = pathlib.Path(home)
    lock = home / MATT_SKILLS_LOCK_RELPATH
    lock.parent.mkdir(parents=True, exist_ok=True)
    if not lock.exists():
        lock.write_text(
            '{"version":3,"skills":{"setup-matt-pocock-skills":{"source":"mattpocock/skills"}}}\n',
            encoding="utf-8",
        )


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


def run_playbook(playbook, state_dir, extra_vars=(), extra_env=None, seed_skills=True):
    env = dict(os.environ)
    b = venv_bin()
    env["PATH"] = f"{STUBS_DIR}{os.pathsep}{b}{os.pathsep}{env.get('PATH', '')}"
    env["STUB_STATE_DIR"] = str(state_dir)
    env["ANSIBLE_PYTHON_INTERPRETER"] = str(b / "python")
    env["ANSIBLE_DEPRECATION_WARNINGS"] = "False"
    # homebrew_path="" disables the modules' hardcoded /usr/local:/opt/homebrew
    # search dirs (they take precedence over PATH), so the stubs in STUBS_DIR win.
    extra_env = dict(extra_env or {})
    # Isolate $HOME so the playbook's skill checks never see the host machine. By
    # default skills count as present (markers only, no lock): unrelated playbook
    # tests stay focused and report changed=0. Pass seed_skills=False for an empty
    # HOME, or extra_env={"HOME": ...} to control the directory yourself.
    home = pathlib.Path(extra_env.get("HOME") or (state_dir.parent / "home"))
    home.mkdir(parents=True, exist_ok=True)
    if seed_skills and "HOME" not in extra_env:
        seed_matt_skill_markers(home)
    env["HOME"] = str(home)
    if extra_env:
        env.update(extra_env)
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
            # Record the env the installer was invoked with: NONINTERACTIVE=1 would
            # make Homebrew's real installer check sudo non-interactively and fail on
            # a fresh Mac — pin that bootstrap does not set it.
            "printf 'NONINTERACTIVE=%s\\n' \"${{NONINTERACTIVE-UNSET}}\" > {0}".format(
                shlex.quote(str(state_dir / "installer-env"))
            ),
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
    # Command-line casks (bin: entries in playbooks/site.yml) are presence-checked
    # on PATH. Plant them here so M2's bootstrap-focused tests treat the inventory
    # as already present, like its seeded brew state. Stubs + test venv + bare
    # system dirs only, so no host brew-managed tools can leak into checks.
    cli_bin = tmp_path / "cli-bin"
    cli_bin.mkdir()
    for name in playbook_bin_casks():
        exe = cli_bin / name
        exe.write_text("#!/bin/sh\n", encoding="utf-8")
        exe.chmod(0o755)
    env["PATH"] = f"{STUBS_DIR}{os.pathsep}{cli_bin}{os.pathsep}{b}{os.pathsep}/usr/bin{os.pathsep}/bin"
    env["STUB_STATE_DIR"] = str(state_dir)
    env["HOMEBREW_PREFIX"] = str(prefix)
    env["FAKE_BREW_INSTALLER"] = str(installer)
    # site.yml presence-checks Oh My Zsh at $ZSH: point it at an existing tmp
    # dir so bootstrap tests never reach its installer (tested in M3).
    omz = tmp_path / "oh-my-zsh"
    omz.mkdir()
    env["ZSH"] = str(omz)
    # Isolate $HOME: bootstrap appends a brew shellenv line to ~/.zprofile,
    # which must never touch the real one. Markers only (no lock) keep M2 focused
    # on bootstrap: the playbook sees the skills as a manual install and leaves them alone.
    home = tmp_path / "home"
    home.mkdir()
    seed_matt_skill_markers(home)
    env["HOME"] = str(home)
    # Empty cask presence dir: the host's real /Applications must not leak into
    # the playbook run that bootstrap drives.
    apps = tmp_path / "apps"
    apps.mkdir()
    env["APPS_DIR"] = str(apps)
    # bootstrap.sh runs playbooks/site.yml when present: give its ansible the
    # same interpreter and warning settings as run_playbook.
    env["ANSIBLE_PYTHON_INTERPRETER"] = str(b / "python")
    env["ANSIBLE_DEPRECATION_WARNINGS"] = "False"

    def run(extra_env=None):
        merged = dict(env)
        if extra_env:
            merged.update(extra_env)
        return subprocess.run(
            ["bash", str(REPO_ROOT / "bootstrap.sh")],
            capture_output=True, text=True, env=merged, cwd=str(REPO_ROOT), timeout=600,
            # Never let a prompt read a real terminal under test: without a TTY on
            # stdin bootstrap must use its default, not hang.
            stdin=subprocess.DEVNULL,
        )

    return SimpleNamespace(
        prefix=prefix, state_dir=state_dir, env=env, install_brew=install_brew, run=run
    )
