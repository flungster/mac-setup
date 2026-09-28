"""M2: bootstrap.sh against the stubs.

Matrix under test (brew x CLT, missing/present) plus the Xcode license
pre-flight, the ansible ensure step and the playbook seam. Nothing real is
installed: every CLI call lands in a stub, "installing Homebrew" just plants
a wrapper around the brew stub, and sudo runs as-is against those stubs.

Since M3, playbooks/site.yml exists and bootstrap runs it: every test seeds
the app inventory as already brew-managed (INVENTORY_* below, mirrors
playbooks/site.yml) so these tests stay focused on the bootstrap steps
themselves. If the inventory grows, grow the seeds here too (or override per
test).
"""
from conftest import invocations, seed_state, state_entries

OFFICIAL_INSTALL_URL = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
INVENTORY_CASKS = ("1password", "iterm2", "visual-studio-code")
INVENTORY_FORMULAS = {"opencode": "1.0.0", "emacs": "30.2", "gh": "2.67.0", "uv": "0.5.4", "shellcheck": "0.10.0"}


def _require_ok(result):
    assert result.returncode == 0, f"bootstrap failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_brew_and_clt_present_installs_nothing(bootstrap):
    bootstrap.install_brew()
    seed_state(bootstrap.state_dir, casks=INVENTORY_CASKS, formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"}, extra={"clt": 1})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    assert not [c for c in calls if c.startswith("curl ")], f"brew installer ran: {calls}"
    assert not [c for c in calls if c.startswith("brew install")], f"something installed: {calls}"
    assert "xcode-select --install" not in calls, f"CLT install triggered: {calls}"
    assert not [c for c in calls if "license" in c], f"CLT-only machine hit the Xcode license gate: {calls}"
    assert calls.count("brew shellenv") == 1, f"shellenv not evaluated once: {calls}"
    # The playbook may legitimately do nothing brew-wise (e.g. 1Password is a
    # real manual install on this machine — ADR-0001): assert it ran at all.
    output = result.stdout + result.stderr  # ansible's stream varies by version
    assert "PLAY RECAP" in output, f"playbook did not run: {output}"


def test_missing_brew_runs_official_installer_once(bootstrap):
    seed_state(bootstrap.state_dir, casks=INVENTORY_CASKS, formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"}, extra={"clt": 1})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    curl_calls = [c for c in calls if c.startswith("curl ")]
    assert len(curl_calls) == 1, f"expected exactly one installer fetch; saw: {curl_calls}"
    assert OFFICIAL_INSTALL_URL in curl_calls[0], f"unexpected install URL: {curl_calls[0]}"

    wrapper = bootstrap.prefix / "bin" / "brew"
    assert wrapper.exists(), "fake installer did not plant a brew at HOMEBREW_PREFIX/bin/brew"
    assert wrapper.stat().st_mode & 0o111, "planted brew is not executable"

    # Fresh-Mac regression: NONINTERACTIVE=1 makes Homebrew's installer check sudo
    # with `sudo -n`, which fails without cached credentials — even for an admin.
    installer_env = (bootstrap.state_dir / "installer-env").read_text().strip()
    assert installer_env == "NONINTERACTIVE=UNSET", (
        f"installer invoked with {installer_env!r} — it must be able to prompt for the password"
    )


def test_missing_clt_triggers_install(bootstrap):
    bootstrap.install_brew()
    seed_state(bootstrap.state_dir, casks=INVENTORY_CASKS, formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    assert calls.count("xcode-select --install") == 1, f"CLT install not triggered exactly once: {calls}"


def test_fresh_mac_runs_both_installs(bootstrap):
    seed_state(bootstrap.state_dir, casks=INVENTORY_CASKS, formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    assert len([c for c in calls if c.startswith("curl ")]) == 1, f"brew installer count wrong: {calls}"
    assert calls.count("xcode-select --install") == 1, f"CLT install count wrong: {calls}"
    assert (bootstrap.prefix / "bin" / "brew").exists(), "fake installer did not plant brew"


def test_missing_ansible_is_installed_via_brew(bootstrap):
    bootstrap.install_brew()
    seed_state(bootstrap.state_dir, casks=INVENTORY_CASKS, formulas=dict(INVENTORY_FORMULAS), extra={"clt": 1})

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
    seed_state(bootstrap.state_dir, casks=INVENTORY_CASKS, formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"}, extra={"clt": 1})

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    installs = [c for c in calls if c.startswith("brew install")]
    assert not installs, f"ansible (or something) was reinstalled: {installs}"


def test_unaccepted_xcode_license_is_accepted_before_brew(bootstrap):
    # Full Xcode active (xcode_version) with an unaccepted license — the state a
    # fresh Xcode install or update leaves behind: xcrun-served tools and
    # `brew` fail until it is sudo-accepted. Bootstrap must clear the gate
    # before touching brew.
    bootstrap.install_brew()
    seed_state(
        bootstrap.state_dir,
        casks=INVENTORY_CASKS,
        formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"},
        extra={"clt": 1, "xcode_version": "26.0"},
    )

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    assert "xcodebuild -license status" in calls, f"license not probed: {calls}"
    assert "sudo xcodebuild -license accept" in calls, f"unaccepted license not accepted: {calls}"
    assert calls.index("xcodebuild -license status") < calls.index("sudo xcodebuild -license accept"), (
        f"accept ran before the probe: {calls}"
    )
    brew_calls = [c for c in calls if c.startswith("brew ")]
    assert brew_calls and calls.index(brew_calls[0]) > calls.index("sudo xcodebuild -license accept"), (
        f"brew ran before the license was accepted: {calls}"
    )
    assert "xcode_license_accepted" in state_entries(bootstrap.state_dir), (
        f"acceptance did not persist: {state_entries(bootstrap.state_dir)}"
    )


def test_accepted_xcode_license_is_not_reaccepted(bootstrap):
    bootstrap.install_brew()
    seed_state(
        bootstrap.state_dir,
        casks=INVENTORY_CASKS,
        formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"},
        extra={"clt": 1, "xcode_version": "26.0", "xcode_license_accepted": 1},
    )

    result = bootstrap.run()
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    assert "xcodebuild -license status" in calls, f"license not probed: {calls}"
    assert "sudo xcodebuild -license accept" not in calls, f"already-accepted license re-accepted: {calls}"
