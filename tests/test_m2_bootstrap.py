"""M2: bootstrap.sh against the stubs.

Matrix under test (brew x CLT, missing/present) plus the ansible ensure step
and the playbook seam. Nothing real is installed: every CLI call lands in a
stub, and "installing Homebrew" just plants a wrapper around the brew stub.
"""
from conftest import invocations, seed_state, state_entries

OFFICIAL_INSTALL_URL = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"


def _require_ok(result):
    assert result.returncode == 0, f"bootstrap failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_brew_and_clt_present_installs_nothing(bootstrap):
    bootstrap.install_brew()
    seed_state(bootstrap.state_dir, formulas={"ansible": "9.0.0"}, extra={"clt": 1})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    assert not [c for c in calls if c.startswith("curl ")], f"brew installer ran: {calls}"
    assert not [c for c in calls if c.startswith("brew install")], f"something installed: {calls}"
    assert "xcode-select --install" not in calls, f"CLT install triggered: {calls}"
    assert calls.count("brew shellenv") == 1, f"shellenv not evaluated once: {calls}"
    assert "playbooks/site.yml not present yet" in result.stderr, result.stderr


def test_missing_brew_runs_official_installer_once(bootstrap):
    seed_state(bootstrap.state_dir, formulas={"ansible": "9.0.0"}, extra={"clt": 1})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    curl_calls = [c for c in calls if c.startswith("curl ")]
    assert len(curl_calls) == 1, f"expected exactly one installer fetch; saw: {curl_calls}"
    assert OFFICIAL_INSTALL_URL in curl_calls[0], f"unexpected install URL: {curl_calls[0]}"

    wrapper = bootstrap.prefix / "bin" / "brew"
    assert wrapper.exists(), "fake installer did not plant a brew at HOMEBREW_PREFIX/bin/brew"
    assert wrapper.stat().st_mode & 0o111, "planted brew is not executable"


def test_missing_clt_triggers_install(bootstrap):
    bootstrap.install_brew()
    seed_state(bootstrap.state_dir, formulas={"ansible": "9.0.0"})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    assert calls.count("xcode-select --install") == 1, f"CLT install not triggered exactly once: {calls}"


def test_fresh_mac_runs_both_installs(bootstrap):
    seed_state(bootstrap.state_dir, formulas={"ansible": "9.0.0"})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    assert len([c for c in calls if c.startswith("curl ")]) == 1, f"brew installer count wrong: {calls}"
    assert calls.count("xcode-select --install") == 1, f"CLT install count wrong: {calls}"
    assert (bootstrap.prefix / "bin" / "brew").exists(), "fake installer did not plant brew"


def test_missing_ansible_is_installed_via_brew(bootstrap):
    bootstrap.install_brew()
    seed_state(bootstrap.state_dir, extra={"clt": 1})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    assert "brew list --formula ansible" in calls, f"ansible presence not checked: {calls}"
    installs = [c for c in calls if c.startswith("brew install")]
    assert len(installs) == 1 and "ansible" in installs[0], f"expected one ansible install; saw: {calls}"
    assert "formula.ansible" in state_entries(bootstrap.state_dir), (
        f"install did not persist to stub state: {state_entries(bootstrap.state_dir)}"
    )


def test_present_ansible_is_not_reinstalled(bootstrap):
    bootstrap.install_brew()
    seed_state(bootstrap.state_dir, formulas={"ansible": "9.0.0"}, extra={"clt": 1})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    installs = [c for c in calls if c.startswith("brew install")]
    assert not installs, f"ansible (or something) was reinstalled: {installs}"
