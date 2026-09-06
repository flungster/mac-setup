"""M1 selftest: the stub harness drives real ansible modules correctly.

These tests pin down the mechanics every later milestone relies on:
install-if-missing, skip-if-present (idempotency), state persistence across
stubs and ansible invocations, and the scoped-upgrade command path.
"""
from conftest import REPO_ROOT, invocations, run_playbook, seed_state, state_entries

PLAYBOOK = REPO_ROOT / "tests" / "selftest" / "site.yml"


def _require_ok(result):
    assert result.returncode == 0, f"playbook failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_fresh_machine_installs_cask_and_formula(stub_state):
    seed_state(stub_state)  # empty state = fresh machine
    _require_ok(run_playbook(PLAYBOOK, stub_state))

    calls = invocations(stub_state)
    assert "brew install --cask fakeapp" in calls, f"cask was not installed; saw: {calls}"
    assert "brew install fakepkg" in calls, f"formula was not installed; saw: {calls}"
    assert "brew upgrade fakeapp fakepkg" in calls, f"scoped upgrade did not run; saw: {calls}"


def test_rerun_after_install_does_not_reinstall(stub_state):
    seed_state(stub_state)  # fresh machine
    _require_ok(run_playbook(PLAYBOOK, stub_state))
    assert any(c.startswith("brew install") for c in invocations(stub_state))

    seen = len(invocations(stub_state))
    _require_ok(run_playbook(PLAYBOOK, stub_state))

    new_calls = invocations(stub_state)[seen:]
    reinstalls = [c for c in new_calls if c.startswith("brew install")]
    assert not reinstalls, f"second run re-installed: {reinstalls} (full log tail: {new_calls})"


def test_up_to_date_machine_makes_no_installs(stub_state):
    seed_state(stub_state, casks=["fakeapp"], formulas={"fakepkg": "2.5.0"})
    _require_ok(run_playbook(PLAYBOOK, stub_state))

    calls = invocations(stub_state)
    installs = [c for c in calls if c.startswith("brew install")]
    assert not installs, f"up-to-date machine still installed: {installs}"


def test_scoped_upgrade_covers_exactly_the_managed_set(stub_state):
    seed_state(stub_state, casks=["fakeapp"], formulas={"fakepkg": "2.5.0"})
    _require_ok(run_playbook(PLAYBOOK, stub_state))

    upgrades = [c for c in invocations(stub_state) if c.startswith("brew upgrade")]
    assert len(upgrades) == 1, f"expected exactly one scoped upgrade call; saw: {upgrades}"
    assert set(upgrades[0].split()[2:]) == {"fakeapp", "fakepkg"}, f"unexpected upgrade scope: {upgrades[0]}"


def test_state_file_updated_after_install(stub_state):
    seed_state(stub_state)  # fresh machine
    _require_ok(run_playbook(PLAYBOOK, stub_state))

    entries = state_entries(stub_state)
    assert "cask.fakeapp" in entries, f"cask install did not persist to stub state: {entries}"
    assert "formula.fakepkg" in entries, f"formula install did not persist to stub state: {entries}"
