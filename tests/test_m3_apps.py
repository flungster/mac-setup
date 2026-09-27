"""M3: playbooks/site.yml against the stubs.

Pins ADR-0001 on the real playbook: manually-present apps (a cask under
apps_dir, a formula as a binary on PATH) are left entirely alone — neither
installed nor upgraded; brew-managed apps get the scoped upgrade. Plus
brew-managed idempotency on the inventory that actually ships.

Tests run with a clean PATH (stubs + bare system dirs) so formula presence
(`command -v`) and management (`brew list`, via stubs) are deterministic no
matter what the host machine has installed.

The default-inventory tests assert against playbooks/site.yml's full cask and
formula list: when you grow the inventory, update those assertions here (and
the M2 seed in tests/test_m2_bootstrap.py).
"""
import os

from conftest import REPO_ROOT, STUBS_DIR, invocations, run_playbook, seed_state

PLAYBOOK = REPO_ROOT / "playbooks" / "site.yml"
# Deterministic PATH: stubs first, then only bare system dirs (no brew-managed
# tools can leak into `command -v` presence checks). Ansible's tmp setup needs /bin.
CLEAN_PATH = f"{STUBS_DIR}{os.pathsep}/usr/bin{os.pathsep}/bin"
CLEAN_ENV = {"PATH": CLEAN_PATH}

# Mirrors playbooks/site.yml (casks and formulas, in inventory order).
INVENTORY_CASKS = ["1password", "iterm2", "visual-studio-code"]
INVENTORY_FORMULAS = ["opencode", "emacs", "gh", "uv"]


def _require_ok(result):
    assert result.returncode == 0, f"playbook failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def _apps_dir(stub_state):
    d = stub_state.parent / "apps"
    d.mkdir(exist_ok=True)
    return d


def _run(stub_state, apps, extra_vars=(), extra_env=None):
    return run_playbook(
        PLAYBOOK, stub_state, extra_vars=(f"apps_dir={apps}", *extra_vars), extra_env=extra_env
    )


def test_fresh_machine_installs_full_inventory_and_upgrades_it(stub_state):
    apps = _apps_dir(stub_state)  # empty: nothing manual either
    seed_state(stub_state)

    _require_ok(_run(stub_state, apps, extra_env=CLEAN_ENV))
    calls = invocations(stub_state)

    for c in INVENTORY_CASKS:
        assert f"brew install --cask {c}" in calls, f"cask was not installed; saw: {calls}"
    for f in INVENTORY_FORMULAS:
        assert f"brew install {f}" in calls, f"formula was not installed; saw: {calls}"
    upgrades = [c for c in calls if c.startswith("brew upgrade")]
    assert len(upgrades) == 1 and upgrades[0].split()[2:] == INVENTORY_CASKS + INVENTORY_FORMULAS, (
        f"scoped upgrade wrong: {upgrades}"
    )


def test_manually_present_cask_is_left_alone(stub_state):
    apps = _apps_dir(stub_state)
    (apps / "1Password.app").mkdir()  # manual install, invisible to brew
    seed_state(stub_state)

    _require_ok(_run(stub_state, apps))
    calls = invocations(stub_state)

    touched = [c for c in calls if "1password" in c and ("install" in c or "upgrade" in c)]
    assert not touched, f"manually-present 1password was touched: {touched}"


def test_missing_formula_is_installed(stub_state):
    apps = _apps_dir(stub_state)
    seed_state(stub_state)

    _require_ok(_run(stub_state, apps, extra_vars=['{"formulas": [{"name": "fakecli"}]}']))
    calls = invocations(stub_state)

    assert "brew install fakecli" in calls, f"formula was not installed; saw: {calls}"


def test_manually_present_formula_is_left_alone(stub_state):
    apps = _apps_dir(stub_state)
    fake_bin = stub_state.parent / "bin"
    fake_bin.mkdir(exist_ok=True)
    (fake_bin / "rustc").write_text("#!/bin/sh\n")  # manually installed tool, on PATH
    (fake_bin / "rustc").chmod(0o755)
    seed_state(stub_state)

    _require_ok(
        _run(
            stub_state,
            apps,
            extra_vars=['{"casks": [], "formulas": [{"name": "rustc"}, {"name": "fakecli"}]}'],
            # Keep the real system dirs: ansible's tmp setup needs /bin. The
            # fake dir goes first so `command -v rustc` finds the manual one.
            extra_env={"PATH": f"{fake_bin}{os.pathsep}{STUBS_DIR}{os.pathsep}{os.environ['PATH']}"},
        )
    )
    calls = invocations(stub_state)

    assert "brew install fakecli" in calls, f"missing formula not installed: {calls}"
    assert "brew install rustc" not in calls, f"manually-present formula was installed: {calls}"
    upgrades = [c for c in calls if c.startswith("brew upgrade")]
    assert len(upgrades) == 1 and set(upgrades[0].split()[2:]) == {"fakecli"}, (
        f"upgrade scope must exclude the manual install: {upgrades}"
    )


def test_rerun_does_not_reinstall_brew_managed(stub_state):
    apps = _apps_dir(stub_state)
    seed_state(stub_state)

    _require_ok(_run(stub_state, apps, extra_env=CLEAN_ENV))
    seen = len(invocations(stub_state))
    _require_ok(_run(stub_state, apps, extra_env=CLEAN_ENV))

    new_calls = invocations(stub_state)[seen:]
    reinstalls = [c for c in new_calls if "install" in c]
    assert not reinstalls, f"second run re-installed: {reinstalls}"


def test_brew_managed_present_app_is_upgraded_not_untouched(stub_state):
    # Present via the on-disk signal AND brew-managed: ADR-0001 keeps manual
    # installs entirely alone but the scoped upgrade still covers whatever brew
    # manages — a rerun is the update path. (Old M3 behavior skipped these from
    # upgrades; this test pins the ADR's consequence, not that.)
    apps = _apps_dir(stub_state)
    (apps / "iTerm.app").mkdir()  # iterm2: present...
    extra_bin = stub_state.parent / "bin"   # ...and gh, as a binary on PATH
    extra_bin.mkdir(exist_ok=True)
    (extra_bin / "gh").write_text("#!/bin/sh\n")
    (extra_bin / "gh").chmod(0o755)
    seed_state(stub_state, casks=["iterm2"], formulas={"gh": "2.0"})  # ...both brew-managed

    _require_ok(
        _run(stub_state, apps, extra_env={"PATH": f"{extra_bin}{os.pathsep}{CLEAN_PATH}"})
    )
    calls = invocations(stub_state)

    assert "brew install --cask iterm2" not in calls, f"present cask reinstalled: {calls}"
    assert "brew install gh" not in calls, f"present formula reinstalled: {calls}"
    upgrades = [c for c in calls if c.startswith("brew upgrade")]
    assert len(upgrades) == 1, f"expected one scoped upgrade; saw: {upgrades}"
    scope = upgrades[0].split()[2:]
    assert set(scope) == set(INVENTORY_CASKS + INVENTORY_FORMULAS), (
        f"managed-but-present apps must stay in the upgrade set: {scope}"
    )
