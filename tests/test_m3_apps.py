"""M3: playbooks/site.yml against the stubs.

Pins ADR-0001 on the real playbook: manually-present apps (a cask under
apps_dir, a formula as a binary on PATH) are left entirely alone — neither
installed nor upgraded. Plus brew-managed idempotency and scoped-upgrade
behavior on the inventory that actually ships.
"""
import os

from conftest import REPO_ROOT, STUBS_DIR, invocations, run_playbook, seed_state

PLAYBOOK = REPO_ROOT / "playbooks" / "site.yml"


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


def test_fresh_machine_installs_missing_cask_and_upgrades_it(stub_state):
    apps = _apps_dir(stub_state)  # empty: nothing manual either
    seed_state(stub_state)

    _require_ok(_run(stub_state, apps))
    calls = invocations(stub_state)

    assert "brew install --cask 1password" in calls, f"cask was not installed; saw: {calls}"
    upgrades = [c for c in calls if c.startswith("brew upgrade")]
    assert len(upgrades) == 1 and upgrades[0].split()[2:] == ["1password"], (
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

    _require_ok(_run(stub_state, apps))
    seen = len(invocations(stub_state))
    _require_ok(_run(stub_state, apps))

    new_calls = invocations(stub_state)[seen:]
    reinstalls = [c for c in new_calls if "install" in c]
    assert not reinstalls, f"second run re-installed: {reinstalls}"
