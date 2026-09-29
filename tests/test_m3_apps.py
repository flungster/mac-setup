"""M3: playbooks/site.yml against the stubs.

Pins ADR-0001 on the real playbook: manually-present apps (a cask under
apps_dir, a formula as a binary on PATH) are left entirely alone — neither
installed nor upgraded; brew-managed apps get the scoped upgrade. Plus
brew-managed idempotency on the inventory that actually ships.

Tests run with a clean PATH (stubs + bare system dirs) so formula presence
(`command -v`) and management (`brew list`, via stubs) are deterministic no
matter what the host machine has installed.

The default-inventory tests assert against playbooks/site.yml's full cask and
formula list — loaded from the playbook itself (INVENTORY_* below), so growing
the inventory cannot desync these tests.
"""
import os

from conftest import (
    REPO_ROOT,
    STUBS_DIR,
    invocations,
    playbook_bin_casks,
    playbook_inventory,
    run_playbook,
    seed_managed_matt_skills,
    seed_state,
)

PLAYBOOK = REPO_ROOT / "playbooks" / "site.yml"
# Deterministic PATH: stubs first, then only bare system dirs (no brew-managed
# tools can leak into `command -v` presence checks). Ansible's tmp setup needs /bin.
CLEAN_PATH = f"{STUBS_DIR}{os.pathsep}/usr/bin{os.pathsep}/bin"
CLEAN_ENV = {"PATH": CLEAN_PATH}

# From playbooks/site.yml (casks and formulas, in inventory order).
INVENTORY_CASKS, INVENTORY_FORMULAS = playbook_inventory()


def _require_ok(result):
    assert result.returncode == 0, f"playbook failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def _apps_dir(stub_state):
    d = stub_state.parent / "apps"
    d.mkdir(exist_ok=True)
    return d


def _omz_dir(stub_state, present=True):
    d = stub_state.parent / "oh-my-zsh"
    if present:
        d.mkdir(exist_ok=True)
    return d


def _run(stub_state, apps, extra_vars=(), extra_env=None, omz_dir=None, seed_skills=True):
    # Oh My Zsh defaults to present (a tmp dir), so tests about brew apps never
    # reach its installer; the Oh My Zsh tests pass their own omz_dir.
    omz = omz_dir if omz_dir is not None else _omz_dir(stub_state)
    return run_playbook(
        PLAYBOOK,
        stub_state,
        extra_vars=(f"apps_dir={apps}", f"oh_my_zsh_dir={omz}", *extra_vars),
        extra_env=extra_env,
        seed_skills=seed_skills,
    )


def _fake_cli_bin(stub_state):
    d = stub_state.parent / "cli-bin"
    d.mkdir(exist_ok=True)
    for name in playbook_bin_casks():
        exe = d / name
        if not exe.exists():
            exe.write_text("#!/bin/sh\n", encoding="utf-8")
        exe.chmod(0o755)
    return d


EMPTY_INVENTORY = ('{"casks": [], "formulas": []}',)


def _recap_changed(result):
    import re

    m = re.search(r"changed=(\d+)", result.stdout)
    assert m, f"no PLAY RECAP in output:\n{result.stdout}"
    return int(m.group(1))


def test_fresh_machine_installs_full_inventory(stub_state):
    apps = _apps_dir(stub_state)  # empty: nothing manual either
    seed_state(stub_state)

    _require_ok(_run(stub_state, apps, extra_env=CLEAN_ENV))
    calls = invocations(stub_state)

    for c in INVENTORY_CASKS:
        assert f"brew install --cask {c}" in calls, f"cask was not installed; saw: {calls}"
    for f in INVENTORY_FORMULAS:
        assert f"brew install {f}" in calls, f"formula was not installed; saw: {calls}"
    # Everything is freshly at latest, so brew has nothing to upgrade.
    assert not [c for c in calls if c.startswith("brew upgrade")], f"unexpected upgrade: {calls}"


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
    # fakecli is freshly at latest, so there is nothing to upgrade. (Scope
    # exclusion of the manual rustc from upgrades has its own test below.)
    assert not [c for c in calls if c.startswith("brew upgrade")], f"unexpected upgrade: {calls}"


def test_manual_install_stays_out_of_upgrade_scope(stub_state):
    # rustc: on PATH but not brew-managed (manual) — must stay out of the
    # upgrade scope. fakecli: brew-managed AND outdated — must be upgraded.
    apps = _apps_dir(stub_state)
    fake_bin = stub_state.parent / "bin"
    fake_bin.mkdir(exist_ok=True)
    (fake_bin / "rustc").write_text("#!/bin/sh\n")  # manually installed tool, on PATH
    (fake_bin / "rustc").chmod(0o755)
    seed_state(stub_state, formulas={"fakecli": "1.0"}, outdated_formulas=["fakecli"])

    _require_ok(
        _run(
            stub_state,
            apps,
            extra_vars=['{"casks": [], "formulas": [{"name": "rustc"}, {"name": "fakecli"}]}'],
            extra_env={"PATH": f"{fake_bin}{os.pathsep}{CLEAN_PATH}"},
        )
    )
    calls = invocations(stub_state)

    assert not [c for c in calls if "rustc" in c and ("install" in c or "upgrade" in c)], (
        f"manually-present rustc was touched: {calls}"
    )
    upgrades = [c for c in calls if c.startswith("brew upgrade")]
    assert len(upgrades) == 1 and set(upgrades[0].split()[2:]) == {"fakecli"}, (
        f"upgrade scope must be exactly the managed outdated set: {upgrades}"
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
    seed_state(stub_state, casks=["iterm2"], formulas={"gh": "2.0"}, outdated_formulas=["gh"])  # ...both brew-managed; gh needs an update

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


def test_up_to_date_run_reports_no_change(stub_state):
    # Re-running on a current machine must be an actual no-op (changed=0), not
    # just "install nothing": the scoped upgrade is gated on `brew outdated`.
    apps = _apps_dir(stub_state)
    seed_state(
        stub_state, casks=list(INVENTORY_CASKS), formulas={f: "1.0" for f in INVENTORY_FORMULAS}
    )

    result = _run(stub_state, apps, extra_env=CLEAN_ENV)
    _require_ok(result)

    assert not [c for c in invocations(stub_state) if c.startswith("brew upgrade")], (
        f"nothing is outdated, yet brew was told to upgrade: {invocations(stub_state)}"
    )
    assert _recap_changed(result) == 0, f"up-to-date run reported changes:\n{result.stdout}"


def test_outdated_app_triggers_scoped_upgrade_and_reports_change(stub_state):
    apps = _apps_dir(stub_state)
    seed_state(
        stub_state, casks=list(INVENTORY_CASKS), formulas={f: "1.0" for f in INVENTORY_FORMULAS},
        outdated_formulas=["gh"],
    )

    result = _run(stub_state, apps, extra_env=CLEAN_ENV)
    _require_ok(result)

    upgrades = [c for c in invocations(stub_state) if c.startswith("brew upgrade")]
    assert len(upgrades) == 1 and set(upgrades[0].split()[2:]) == set(INVENTORY_CASKS + INVENTORY_FORMULAS), (
        f"scoped upgrade wrong: {upgrades}"
    )
    assert _recap_changed(result) == 1, f"upgrade did not report a change:\n{result.stdout}"


def _fake_omz_installer(stub_state):
    """A stand-in for Oh My Zsh's install.sh, fetched via file:// in tests.

    Records its args and $ZSH, then creates $ZSH like the real installer's clone.
    Returns (script_path, record_file).
    """
    record = stub_state / "omz-installer"
    script = stub_state.parent / "fake-omz-install.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"printf 'args=%s\\nZSH=%s\\n' \"$*\" \"$ZSH\" >> '{record}'\n"
        "mkdir -p \"$ZSH\"\n"
    )
    return script, record


def test_missing_oh_my_zsh_is_installed_once_via_official_script(stub_state):
    apps = _apps_dir(stub_state)
    omz = _omz_dir(stub_state, present=False)
    installer, record = _fake_omz_installer(stub_state)
    seed_state(stub_state)

    _require_ok(
        _run(stub_state, apps, extra_env=CLEAN_ENV, omz_dir=omz,
             extra_vars=(f"oh_my_zsh_install_url=file://{installer}",))
    )

    # Unattended (no chsh / no interactive zsh) and never clobber an existing ~/.zshrc.
    assert record.read_text().splitlines() == ["args=--unattended --keep-zshrc", f"ZSH={omz}"], (
        f"installer invoked wrong: {record.read_text()!r}"
    )
    assert omz.is_dir(), "Oh My Zsh dir not created"

    # Rerun: present now, so the installer must not run again.
    _require_ok(
        _run(stub_state, apps, extra_env=CLEAN_ENV, omz_dir=omz,
             extra_vars=(f"oh_my_zsh_install_url=file://{installer}",))
    )
    assert record.read_text().count("\n") == 2, f"present Oh My Zsh re-installed: {record.read_text()!r}"


def test_present_oh_my_zsh_is_left_alone(stub_state):
    apps = _apps_dir(stub_state)
    omz = _omz_dir(stub_state, present=True)  # e.g. a manual install
    _, record = _fake_omz_installer(stub_state)
    seed_state(stub_state)

    _require_ok(_run(stub_state, apps, extra_env=CLEAN_ENV, omz_dir=omz))

    assert not record.exists(), f"present Oh My Zsh was reinstalled: {record.read_text()!r}"


def test_oh_my_zsh_installer_download_failure_fails_run(stub_state):
    # A failed installer download must fail the run, not leave a half-setup machine.
    apps = _apps_dir(stub_state)
    omz = _omz_dir(stub_state, present=False)
    seed_state(stub_state)

    result = _run(
        stub_state, apps, extra_env=CLEAN_ENV, omz_dir=omz,
        extra_vars=("oh_my_zsh_install_url=file:///nonexistent/oh-my-zsh-install.sh",),
    )

    assert result.returncode != 0, f"run succeeded despite failed installer download:\n{result.stdout}"
    assert not omz.is_dir(), "Oh My Zsh dir created despite failed download"


def _fake_hermes_installer(stub_state):
    """A stand-in for Hermes Agent's install.sh, fetched via file:// in tests.

    Records its args and $HERMES_HOME, then creates the source checkout like the
    real installer. Returns (script_path, record_file).
    """
    record = stub_state / "hermes-installer"
    script = stub_state.parent / "fake-hermes-install-src.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"printf 'args=%s\\nHERMES_HOME=%s\\n' \"$*\" \"${{HERMES_HOME}}\" >> '{record}'\n"
        'mkdir -p "${HERMES_HOME}/hermes-agent"\n'
    )
    return script, record


def _hermes_extra_vars(stub_state, installer_src):
    # hermes_installer is the get_url destination: pin it into tmp so tests never
    # touch (or rely on) the real $TMPDIR.
    return (
        "install_hermes_agent=true",
        f"hermes_install_url=file://{installer_src}",
        f"hermes_installer={stub_state.parent / 'fake-hermes-install.sh'}",
    )


def test_hermes_flag_off_is_a_noop(stub_state):
    # The playbook run with no opt-in (the default) must not even fetch the installer.
    apps = _apps_dir(stub_state)
    seed_state(stub_state)

    result = _run(
        stub_state, apps, extra_env=CLEAN_ENV,
        extra_vars=(EMPTY_INVENTORY[0], f"hermes_installer={stub_state.parent / 'fake-hermes-install.sh'}"),
    )
    _require_ok(result)

    assert not (stub_state.parent / "fake-hermes-install.sh").exists(), "installer was fetched without opt-in"
    assert not (stub_state.parent / "home" / ".hermes").exists(), "Hermes installed without opt-in"


def test_hermes_flag_on_installs_when_missing(stub_state):
    apps = _apps_dir(stub_state)
    installer, record = _fake_hermes_installer(stub_state)
    seed_state(stub_state)

    _require_ok(
        _run(stub_state, apps, extra_env=CLEAN_ENV,
             extra_vars=(EMPTY_INVENTORY[0], *_hermes_extra_vars(stub_state, installer)))
    )

    hermes_home = stub_state.parent / "home" / ".hermes"
    # Non-interactive (no setup wizard) and the data dir pinned to where presence is checked.
    assert record.read_text().splitlines() == [f"args=--non-interactive", f"HERMES_HOME={hermes_home}"], (
        f"installer invoked wrong: {record.read_text()!r}"
    )
    assert (hermes_home / "hermes-agent").is_dir(), "Hermes checkout not created"

    # Rerun: present now, so the installer must not run again.
    _require_ok(
        _run(stub_state, apps, extra_env=CLEAN_ENV,
             extra_vars=(EMPTY_INVENTORY[0], *_hermes_extra_vars(stub_state, installer)))
    )
    assert record.read_text().count("\n") == 2, f"present Hermes re-installed: {record.read_text()!r}"


def test_present_hermes_is_left_alone(stub_state):
    # e.g. a manual install: present, so the installer is neither fetched nor run —
    # even with opt-in on (ADR-0001). The dead URL would fail the run if a fetch happened.
    apps = _apps_dir(stub_state)
    (stub_state.parent / "home" / ".hermes" / "hermes-agent").mkdir(parents=True)
    seed_state(stub_state)

    _require_ok(
        _run(stub_state, apps, extra_env=CLEAN_ENV,
             extra_vars=(EMPTY_INVENTORY[0], "install_hermes_agent=true",
                         f"hermes_install_url=file:///nonexistent/hermes-install.sh"))
    )

    assert not (stub_state / "hermes-installer").exists(), f"present Hermes was touched: {invocations(stub_state)}"


def test_hermes_installer_download_failure_fails_run(stub_state):
    # A failed installer download must fail the run, not leave a half-setup machine.
    apps = _apps_dir(stub_state)
    seed_state(stub_state)

    result = _run(
        stub_state, apps, extra_env=CLEAN_ENV,
        extra_vars=(EMPTY_INVENTORY[0], "install_hermes_agent=true",
                    f"hermes_install_url=file:///nonexistent/hermes-install.sh"),
    )

    assert result.returncode != 0, f"run succeeded despite failed installer download:\n{result.stdout}"
    assert not (stub_state.parent / "home" / ".hermes").exists(), "Hermes dir created despite failed download"


def test_manually_present_command_line_cask_is_left_alone(stub_state):
    apps = _apps_dir(stub_state)
    cli_bin = _fake_cli_bin(stub_state)  # claude/codex on PATH, invisible to brew
    seed_state(stub_state)

    _require_ok(
        _run(
            stub_state, apps,
            extra_vars=['{"casks": [{"name": "claude-code", "bin": "claude"}], "formulas": []}'],
            extra_env={"PATH": f"{cli_bin}{os.pathsep}{CLEAN_PATH}"},
        )
    )
    calls = invocations(stub_state)

    touched = [c for c in calls if "claude-code" in c and ("install" in c or "upgrade" in c)]
    assert not touched, f"manually-present claude-code was touched: {touched}"


def test_command_line_cask_rerun_does_not_reinstall_brew_managed(stub_state):
    apps = _apps_dir(stub_state)
    cli_bin = _fake_cli_bin(stub_state)  # present via PATH...
    seed_state(stub_state, casks=["claude-code"])  # ...and brew-managed

    _require_ok(
        _run(
            stub_state, apps,
            extra_vars=['{"casks": [{"name": "claude-code", "bin": "claude"}], "formulas": []}'],
            extra_env={"PATH": f"{cli_bin}{os.pathsep}{CLEAN_PATH}"},
        )
    )
    calls = invocations(stub_state)

    assert "brew install --cask claude-code" not in calls, f"present cask reinstalled: {calls}"


def test_missing_matt_skills_are_installed_once_then_updated_on_rerun(stub_state):
    apps = _apps_dir(stub_state)
    seed_state(stub_state)

    result = _run(stub_state, apps, extra_vars=EMPTY_INVENTORY, seed_skills=False)
    _require_ok(result)
    calls = invocations(stub_state)

    adds = [c for c in calls if c.startswith("npx ") and " add " in c]
    assert len(adds) == 1, f"skills installer ran {len(adds)} times: {calls}"
    assert adds[0] == (
        "npx -y skills@latest add mattpocock/skills --global"
        " --skill * --agent codex --agent claude-code --yes"
    ), f"unexpected skills install command: {adds[0]!r}"
    assert not [c for c in calls if " update " in c], f"update ran immediately after install: {calls}"

    home = stub_state.parent / "home"
    assert (home / ".agents/skills/setup-matt-pocock-skills/SKILL.md").exists()
    assert (home / ".claude/skills/setup-matt-pocock-skills/SKILL.md").exists()
    assert (home / ".agents/.skill-lock.json").exists()

    seen = len(invocations(stub_state))
    result2 = _run(stub_state, apps, extra_vars=EMPTY_INVENTORY, seed_skills=False)
    _require_ok(result2)
    new_calls = invocations(stub_state)[seen:]

    assert not [c for c in new_calls if " add " in c], f"rerun reinstalled skills: {new_calls}"
    updates = [c for c in new_calls if c.startswith("npx ") and " update " in c]
    assert len(updates) == 1, f"rerun did not update skills exactly once: {new_calls}"


def test_present_matt_skills_without_lock_are_left_alone(stub_state):
    # Markers but no installer lock = a manual install: ADR-0001 leaves it alone.
    apps = _apps_dir(stub_state)
    seed_state(stub_state)

    _require_ok(_run(stub_state, apps, extra_vars=EMPTY_INVENTORY))  # default: markers only
    calls = invocations(stub_state)

    assert not [c for c in calls if c.startswith("npx ")], f"manual skills were touched: {calls}"


def test_managed_matt_skills_update_reports_no_change_when_current(stub_state):
    apps = _apps_dir(stub_state)
    seed_state(stub_state)
    home = stub_state.parent / "managed-skills-home"
    seed_managed_matt_skills(home)

    result = _run(
        stub_state, apps, extra_vars=EMPTY_INVENTORY,
        extra_env={"HOME": str(home)}, seed_skills=False,
    )
    _require_ok(result)
    calls = invocations(stub_state)

    assert not [c for c in calls if " add " in c], f"managed skills were reinstalled: {calls}"
    updates = [c for c in calls if " update " in c]
    assert len(updates) == 1, f"managed skills were not updated exactly once: {calls}"
    assert _recap_changed(result) == 0, f"current skills update reported a change:\n{result.stdout}"


def test_managed_matt_skills_update_reports_change_when_updated(stub_state):
    apps = _apps_dir(stub_state)
    home = stub_state.parent / "managed-skills-home"
    seed_managed_matt_skills(home)
    seed_state(stub_state, extra={"skills.outdated": "1"})

    result = _run(
        stub_state, apps, extra_vars=EMPTY_INVENTORY,
        extra_env={"HOME": str(home)}, seed_skills=False,
    )
    _require_ok(result)
    calls = invocations(stub_state)

    updates = [c for c in calls if " update " in c]
    assert len(updates) == 1, f"managed skills were not updated: {calls}"
    assert _recap_changed(result) == 1, f"skills update did not report a change:\n{result.stdout}"


def test_matt_skills_installer_failure_fails_run(stub_state):
    apps = _apps_dir(stub_state)
    seed_state(stub_state, extra={"skills.fail": "1"})

    result = _run(stub_state, apps, extra_vars=EMPTY_INVENTORY, seed_skills=False)

    assert result.returncode != 0, f"run succeeded despite failed skills installer:\n{result.stdout}"
    home = stub_state.parent / "home"
    assert not (home / ".agents/skills/setup-matt-pocock-skills/SKILL.md").exists(), (
        "partial skills install left behind"
    )
