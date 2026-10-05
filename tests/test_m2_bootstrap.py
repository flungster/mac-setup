"""M2: bootstrap.sh against the stubs.

Matrix under test (brew x CLT, missing/present) plus the Xcode license
pre-flight, the ansible ensure step and the playbook seam. Nothing real is
installed: every CLI call lands in a stub, "installing Homebrew" just plants
a wrapper around the brew stub, and sudo runs as-is against those stubs.

Since M3, playbooks/site.yml exists and bootstrap runs it: every test seeds
the app inventory as already brew-managed (INVENTORY_* below, loaded from the
playbook itself) so these tests stay focused on the bootstrap steps themselves.

The environment is hermetic: stubs + test venv + bare system dirs on PATH,
$HOME and the cask presence dir ($APPS_DIR) point at tmp dirs — nothing from
the host machine can influence the run.

The agents VM is opt-in behind a bootstrap question (PROVISION_AGENTS_VM can pre-
answer it for automation): its plumbing gets tests below, using a recording
ansible-playbook shim on PATH (the playbooks themselves are tested in M3/M5). Two
pseudo-terminal tests drive the real prompt end to end.
"""
import os
import select
import shlex
import subprocess

from conftest import REPO_ROOT, invocations, playbook_inventory, seed_state, state_entries

OFFICIAL_INSTALL_URL = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
# Mirrors playbooks/site.yml (loaded from there — don't duplicate the list).
INVENTORY_CASKS = tuple(playbook_inventory()[0])
# Versions are irrelevant to the stubs; one value keeps seeding terse.
INVENTORY_FORMULAS = {name: "1.0" for name in playbook_inventory()[1]}


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
    assert "xcodebuild -license check" in calls, f"license not probed: {calls}"
    assert "sudo xcodebuild -license accept" in calls, f"unaccepted license not accepted: {calls}"
    assert calls.index("xcodebuild -license check") < calls.index("sudo xcodebuild -license accept"), (
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
    assert "xcodebuild -license check" in calls, f"license not probed: {calls}"
    assert "sudo xcodebuild -license accept" not in calls, f"already-accepted license re-accepted: {calls}"


def test_homebrew_downloader_failure_aborts(bootstrap):
    # A failed download must fail the run, not silently install nothing: with
    # `bash -c "$(curl ...)"` a dead network runs an empty script and exits 0.
    seed_state(bootstrap.state_dir, casks=INVENTORY_CASKS, formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"}, extra={"clt": 1})
    missing = bootstrap.state_dir / "no-such-installer"

    result = bootstrap.run(extra_env={"FAKE_BREW_INSTALLER": str(missing)})

    assert result.returncode != 0, f"bootstrap succeeded despite failed download:\n{result.stdout}\n{result.stderr}"
    assert "could not download Homebrew installer" in result.stderr, f"no clear error: {result.stderr}"
    assert not (bootstrap.prefix / "bin" / "brew").exists(), "partial install left behind: brew was planted"


def test_clt_install_is_waited_for(bootstrap):
    # The CLT install is user-driven and asynchronous: bootstrap must keep
    # polling until it finishes, not race the Homebrew installer into a second install.
    bootstrap.install_brew()
    seed_state(bootstrap.state_dir, casks=INVENTORY_CASKS, formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"})

    result = bootstrap.run(extra_env={"CLT_PENDING_POLLS": "2", "CLT_POLL_INTERVAL": "0"})
    _require_ok(result)

    calls = invocations(bootstrap.state_dir)
    assert calls.count("xcode-select --install") == 1, f"CLT install triggered more than once: {calls}"
    # Pre-check + two polls inside the wait loop (+ one more from the Xcode license step).
    assert calls.count("xcode-select -p") >= 3, f"bootstrap did not wait for the CLT install: {calls}"


def test_clt_install_timeout_fails(bootstrap):
    bootstrap.install_brew()
    seed_state(bootstrap.state_dir, casks=INVENTORY_CASKS, formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"})

    # 10000 polls can't finish within the 2s timeout even at ~ms per poll.
    result = bootstrap.run(
        extra_env={"CLT_PENDING_POLLS": "10000", "CLT_POLL_INTERVAL": "0", "CLT_WAIT_SECONDS": "2"}
    )

    assert result.returncode != 0, f"bootstrap succeeded although the CLT install never finished:\n{result.stderr}"
    assert "did not finish within" in result.stderr, f"no timeout message: {result.stderr}"
    assert invocations(bootstrap.state_dir).count("xcode-select --install") == 1, "CLT install was retried"


def test_brew_shellenv_added_to_zprofile_once(bootstrap):
    # Fresh terminals must find brew: bootstrap appends the shellenv line to
    # ~/.zprofile, exactly once (re-runs are the update path).
    bootstrap.install_brew()
    seed_state(bootstrap.state_dir, casks=INVENTORY_CASKS, formulas={**INVENTORY_FORMULAS, "ansible": "9.0.0"}, extra={"clt": 1})

    _require_ok(bootstrap.run())
    zprofile = bootstrap.env["HOME"] + "/.zprofile"
    line = f'eval "$({bootstrap.prefix}/bin/brew shellenv)"'

    def zprofile_lines():
        with open(zprofile, encoding="utf-8") as f:
            return [l.rstrip("\n") for l in f]

    assert zprofile_lines().count(line) == 1, f"brew shellenv line not added exactly once: {zprofile_lines()}"

    _require_ok(bootstrap.run())
    assert zprofile_lines().count(line) == 1, f"re-run duplicated the brew shellenv line: {zprofile_lines()}"


# ---- agents VM: the opt-in question and its plumbing ---------------------------
#
# A shim named ansible-playbook on PATH records bootstrap's arguments (one line per
# invocation) and exits 0, so these tests pin what is passed without running the
# playbooks (their own behaviour has M3/M5 tests). PROVISION_AGENTS_VM pre-answers
# the prompt; AGENTS_VAULT_SECRETS_FILE names a non-default secrets file (bootstrap
# must find it before running anything, and forwards its path as -e).


def _record_playbook_args(bootstrap):
    """env: a PATH whose ansible-playbook records bootstrap's args, then exits 0."""
    shim_dir = bootstrap.state_dir.parent / "pb-shim"
    shim_dir.mkdir(exist_ok=True)
    args_log = bootstrap.state_dir / "playbook-args.log"
    shim = shim_dir / "ansible-playbook"
    shim.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(args_log))}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return {"PATH": f"{shim_dir}{os.pathsep}{bootstrap.env['PATH']}"}


def _playbook_args(bootstrap):
    return (bootstrap.state_dir / "playbook-args.log").read_text(encoding="utf-8")


def _seed_managed(bootstrap):
    seed_state(
        bootstrap.state_dir, casks=INVENTORY_CASKS,
        formulas={**INVENTORY_FORMULAS, "ansible": "9.0"}, extra={"clt": 1},
    )


def _playbook_calls(bootstrap):
    return [l for l in _playbook_args(bootstrap).splitlines() if l]


def _secrets_file(bootstrap, missing=False):
    """A secrets file for the opt-in pre-flight; `missing` points at an absent path."""
    p = bootstrap.state_dir / ("secrets-missing.yml" if missing else "secrets.yml")
    if not missing:
        p.write_text("anthropic_api_key: stub\n", encoding="utf-8")
    return str(p)


def test_agents_vm_not_provisioned_without_a_terminal(bootstrap):
    # No terminal on stdin and no pre-answer: the prompt cannot be shown, so the
    # default (No) applies — one playbook, and the skip is logged. PROVISION_AGENTS_VM
    # is pinned empty so a developer's environment cannot pre-answer for the test.
    bootstrap.install_brew()
    _seed_managed(bootstrap)

    env = _record_playbook_args(bootstrap)
    env["PROVISION_AGENTS_VM"] = ""

    result = bootstrap.run(extra_env=env)
    _require_ok(result)
    calls = _playbook_calls(bootstrap)

    assert len(calls) == 1, f"expected only the site playbook; saw: {calls}"
    assert "playbooks/site.yml" in calls[0] and "agents-vm" not in calls[0], (
        f"default run touched the agents VM playbook: {calls}"
    )
    assert "no terminal attached" in result.stderr, (
        f"the no-terminal default was not logged: {result.stderr}"
    )


def test_agents_vm_opt_in_runs_the_second_playbook_with_asked_vault_password(bootstrap):
    bootstrap.install_brew()
    _seed_managed(bootstrap)

    env = _record_playbook_args(bootstrap)
    env["PROVISION_AGENTS_VM"] = "1"
    env["AGENTS_VAULT_SECRETS_FILE"] = _secrets_file(bootstrap)

    result = bootstrap.run(extra_env=env)
    _require_ok(result)
    calls = _playbook_calls(bootstrap)

    assert len(calls) == 2, f"expected site + agents-vm playbooks; saw: {calls}"
    assert "playbooks/site.yml" in calls[0], f"site playbook not run first: {calls}"
    assert "playbooks/agents-vm.yml" in calls[1], f"opt-in not passed through: {calls}"
    # No vault password file given → ansible is asked interactively, not left to die.
    assert "--ask-vault-pass" in calls[1], f"vault password not asked for: {calls}"
    assert "--vault-password-file" not in calls[1], (
        f"no vault password file given, yet one was passed: {calls}"
    )
    assert f"-e agents_vm_secrets_file={env['AGENTS_VAULT_SECRETS_FILE']}" in calls[1], (
        f"secrets file path not forwarded: {calls}"
    )


def test_agents_vm_opt_in_forwards_vault_password_file(bootstrap):
    bootstrap.install_brew()
    _seed_managed(bootstrap)

    vault_file = bootstrap.state_dir / "vault-pass"
    vault_file.write_text("stub-password\n", encoding="utf-8")

    env = _record_playbook_args(bootstrap)
    env["PROVISION_AGENTS_VM"] = "1"
    env["AGENTS_VAULT_PASSWORD_FILE"] = str(vault_file)
    env["AGENTS_VAULT_SECRETS_FILE"] = _secrets_file(bootstrap)

    result = bootstrap.run(extra_env=env)
    _require_ok(result)
    calls = _playbook_calls(bootstrap)

    assert len(calls) == 2, f"expected site + agents-vm playbooks; saw: {calls}"
    assert "--vault-password-file" in calls[1] and str(vault_file) in calls[1], (
        f"vault password file not forwarded: {calls}"
    )
    assert "--ask-vault-pass" not in calls[1], (
        f"a vault password file was given, yet ansible was also asked: {calls}"
    )


def test_agents_vm_invalid_opt_in_fails_before_any_playbook(bootstrap):
    bootstrap.install_brew()
    _seed_managed(bootstrap)

    env = _record_playbook_args(bootstrap)
    env["PROVISION_AGENTS_VM"] = "banana"

    result = bootstrap.run(extra_env=env)

    assert result.returncode != 0, f"bootstrap succeeded with a bad flag:\n{result.stderr}"
    assert "PROVISION_AGENTS_VM must be" in result.stderr, f"no clear error: {result.stderr}"
    assert not (bootstrap.state_dir / "playbook-args.log").exists(), (
        f"a bad opt-in must fail before any playbook runs: {_playbook_args(bootstrap)}"
    )


def test_agents_vm_yes_without_secrets_file_fails_before_any_playbook(bootstrap):
    # Opting in without the secrets file must stop bootstrap immediately — before
    # site.yml runs, i.e. before anything is installed at all.
    bootstrap.install_brew()
    _seed_managed(bootstrap)

    env = _record_playbook_args(bootstrap)
    env["PROVISION_AGENTS_VM"] = "1"
    missing = _secrets_file(bootstrap, missing=True)
    env["AGENTS_VAULT_SECRETS_FILE"] = missing

    result = bootstrap.run(extra_env=env)

    assert result.returncode != 0, f"bootstrap succeeded without a secrets file:\n{result.stderr}"
    assert missing in result.stderr, f"the missing path was not named: {result.stderr}"
    assert ".example" in result.stderr, f"no pointer to the template: {result.stderr}"
    assert not (bootstrap.state_dir / "playbook-args.log").exists(), (
        f"a 'yes' without secrets must fail before any playbook runs: {_playbook_args(bootstrap)}"
    )


def _run_with_tty(bootstrap, extra_env=None, tty_input=b"y\n"):
    """Run bootstrap.sh with a pseudo-terminal on stdin (the interactive prompt path).

    Returns (returncode, transcript); `tty_input` is what the "user" types. Only
    stdin goes through the pty; all output still comes back on a plain pipe, so the
    transcript is readable and assertable (e.g. that the prompt was actually shown).
    """
    import pty

    merged = dict(bootstrap.env)
    if extra_env:
        merged.update(extra_env)
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["bash", str(REPO_ROOT / "bootstrap.sh")],
        stdin=slave_fd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=merged,
        cwd=str(REPO_ROOT), close_fds=True,
    )
    # Popen has given the child its own end of the pty; drop ours. The line
    # discipline buffers `tty_input` until bootstrap's `read` consumes it.
    os.close(slave_fd)
    os.write(master_fd, tty_input)
    chunks = []  # read the output pipe to EOF; bounded so a stuck run fails loudly
    while True:
        ready, _, _ = select.select([proc.stdout], [], [], 120)
        if not ready:
            proc.kill()
            raise TimeoutError(
                f"bootstrap did not exit under a TTY; transcript so far: {b''.join(chunks)!r}"
            )
        data = os.read(proc.stdout.fileno(), 65536)
        if not data:
            break
        chunks.append(data)
    rc = proc.wait(timeout=60)
    os.close(master_fd)
    return rc, b"".join(chunks).decode(errors="replace")


def test_agents_vm_prompt_yes_provisions(bootstrap):
    # The real prompt, answered with y: both playbooks run (the agents-VM one asking
    # for the vault password interactively) — hence the pty and the visible question.
    bootstrap.install_brew()
    _seed_managed(bootstrap)

    env = _record_playbook_args(bootstrap)
    env["PROVISION_AGENTS_VM"] = ""   # the prompt itself must answer, not a pre-answer
    env["AGENTS_VAULT_SECRETS_FILE"] = _secrets_file(bootstrap)

    rc, transcript = _run_with_tty(bootstrap, extra_env=env, tty_input=b"y\n")
    assert rc == 0, f"bootstrap failed under a TTY:\n{transcript}"
    assert "Install/update OrbStack and the agents VM" in transcript, f"prompt not shown: {transcript}"
    calls = _playbook_calls(bootstrap)

    assert len(calls) == 2, f"'y' at the prompt must run both playbooks: {calls}"
    assert "playbooks/agents-vm.yml" in calls[1] and "--ask-vault-pass" in calls[1], (
        f"'y' not passed through with an interactive vault password: {calls}"
    )


def test_agents_vm_prompt_bare_enter_is_no(bootstrap):
    # The prompt's default is No: a bare Enter declines — and it must be the prompt
    # that answered (no pre-answer env var set), hence the pty and visible question.
    bootstrap.install_brew()
    _seed_managed(bootstrap)

    env = _record_playbook_args(bootstrap)
    env["PROVISION_AGENTS_VM"] = ""   # the prompt itself must answer, not a pre-answer

    rc, transcript = _run_with_tty(bootstrap, extra_env=env, tty_input=b"\n")
    assert rc == 0, f"bootstrap failed under a TTY:\n{transcript}"
    assert "Install/update OrbStack and the agents VM" in transcript, f"prompt not shown: {transcript}"
    calls = _playbook_calls(bootstrap)

    assert len(calls) == 1, f"bare Enter must decline (one playbook only): {calls}"
    assert "skipping" in transcript, f"the decline was not logged: {transcript}"

