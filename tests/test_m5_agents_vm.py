"""M5: playbooks/agents-vm.yml against the stubs.

The playbook has two halves (both imported by playbooks/agents-vm.yml): the Mac
side (OrbStack ceilings + creating the isolated machine, agents-vm-mac.yml) and
the Linux side inside it (agents-vm-linux.yml: base packages + GitHub access, the
OpenCode server, Matt Pocock skills, Hermes Agent with dashboard/Telegram, and
read-only Gmail/Calendar via workspace-mcp). This file tests both offline: the Mac
half end-to-end against the `orb` stub, and the Linux half mapped back onto
localhost with every path pointed at tmp dirs (agents_vm_home/root/workspace) and
all CLI calls stubbed.

The secrets file is a plain (unencrypted) YAML in tests, passed via
-e agents_vm_secrets_file=...: the playbook treats vaulted and plain files alike.

Nothing real is installed or created outside tmp dirs: the stubs record every call
in invocations.log and keep machine/config/service state in state.env.
"""
import os

from conftest import REPO_ROOT, STUBS_DIR, invocations, run_playbook, seed_state, venv_bin

PARENT_PLAYBOOK = REPO_ROOT / "playbooks" / "agents-vm.yml"
MAC_PLAYBOOK = REPO_ROOT / "playbooks" / "agents-vm-mac.yml"
LINUX_PLAYBOOK = REPO_ROOT / "playbooks" / "agents-vm-linux.yml"


def _vars_agents_vm():
    """playbooks/vars_agents_vm.yml as a dict — the source of truth for these knobs.

    Tests must not carry their own copy (same rule as playbook_inventory in
    conftest): a var renamed or dropped there would desync these assertions. The file
    parses as plain YAML — its {{ ... }} values are just strings to the loader. Loading
    also asserts every key below exists (the plan asks M5 to pin gmail_accounts)."""
    import yaml

    with open(REPO_ROOT / "playbooks" / "vars_agents_vm.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


GMAIL_ACCOUNTS = tuple(_vars_agents_vm()["gmail_accounts"])


def _write_secrets(stub_state, **overrides):
    """A plain (unencrypted) secrets file; the playbook does not care which."""
    import yaml

    values = {
        "anthropic_api_key": "sk-ant-stub",
        "hermes_dashboard_password": "stub-password",
    }
    values.update(overrides)
    path = stub_state.parent / "secrets.yml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(values, f)
    return str(path)


def _run(stub_state, secrets_path=None, workspace=None, extra_vars=(), extra_env=None):
    if secrets_path is None:
        secrets_path = _write_secrets(stub_state)
    vars_ = [f"agents_vm_secrets_file={secrets_path}"]
    if workspace is not None:
        vars_.append(f"agents_vm_workspace_host_path={workspace}")
    return run_playbook(
        MAC_PLAYBOOK, stub_state, extra_vars=tuple(vars_) + tuple(extra_vars),
        seed_skills=False, extra_env=extra_env,
    )


def _mac_install_env(stub_state, installed_bin=True):
    """A hermetic PATH for the OrbStack install-path tests.

    A symlink farm with every stub except `orb` (so 'command -v orb' genuinely
    fails until an install provides it), plus — by default — the installed-bin dir
    where 'brew install --cask orbstack' plants a working CLI (the brew stub emulates
    the cask's postinstall). APPS_DIR is an empty tmp dir so this host's
    /Applications cannot leak into the role's presence checks. extra_env replaces
    PATH wholesale, so everything a shell task needs must be in it: the farm (which
    carries brew and friends), the venv bin, bare system dirs.
    """
    farm = stub_state.parent / "mac-bin"
    farm.mkdir(exist_ok=True)
    for f in STUBS_DIR.iterdir():
        if not f.is_file() or f.name == "orb":
            continue
        link = farm / f.name
        if not link.exists():
            link.symlink_to(f)
    apps = stub_state.parent / "apps-empty"
    apps.mkdir(exist_ok=True)
    parts = [str(farm)]
    if installed_bin:
        parts.append(str(stub_state.parent / "installed-bin"))
    return {
        "PATH": os.pathsep.join(parts + [str(venv_bin()), "/usr/bin", "/bin"]),
        "APPS_DIR": str(apps),
    }


def _empty_apps_dir(stub_state):
    apps = stub_state.parent / "apps-empty"
    apps.mkdir(exist_ok=True)
    return str(apps)


def _require_ok(result):
    assert result.returncode == 0, f"playbook failed:\n{result.stdout}"


# Every Mac-side test pins APPS_DIR at an empty tmp dir: the role's OrbStack.app
# presence check must never see this host's /Applications (hermeticity, like M2/M3).
def _mac_env_default(stub_state):
    return {"APPS_DIR": _empty_apps_dir(stub_state)}


def test_fresh_run_creates_the_vm_and_sets_ceilings(stub_state):
    workspace = stub_state.parent / "agent_workspaces"

    _require_ok(_run(stub_state, workspace=str(workspace), extra_env=_mac_env_default(stub_state)))
    inv = invocations(stub_state)

    assert workspace.is_dir(), "workspace folder not created on this Mac"
    mount = f"{workspace}:/workspace"
    assert inv.count(f"orb create --isolated --mount {mount} ubuntu:noble agents") == 1, (
        f"machine not created exactly once: {inv}"
    )
    assert inv.count("orb config set memory_mib 12288") == 1, f"memory ceiling: {inv}"
    assert inv.count("orb config set cpu 6") == 1, f"cpu ceiling: {inv}"
    assert inv.count("orb config set machines.expose_ports_to_lan true") == 1, (
        f"LAN exposure: {inv}"
    )
    assert not any(l.startswith("orb restart") for l in inv), f"fresh machine restarted: {inv}"


def test_rerun_is_a_noop(stub_state):
    workspace = stub_state.parent / "agent_workspaces"

    _require_ok(_run(stub_state, workspace=str(workspace), extra_env=_mac_env_default(stub_state)))
    baseline = len(invocations(stub_state))

    _require_ok(_run(stub_state, workspace=str(workspace), extra_env=_mac_env_default(stub_state)))
    new = invocations(stub_state)[baseline:]

    assert not any(l.startswith("orb create") for l in new), f"machine recreated: {new}"
    assert not any(l.startswith("orb config set") for l in new), f"re-run changed settings: {new}"
    assert not any(l.startswith("orb restart") for l in new), f"re-run restarted the VM: {new}"


def test_stopped_orbstack_is_started_first(stub_state):
    seed_state(stub_state, extra={"orb.stopped": 1})
    workspace = stub_state.parent / "agent_workspaces"

    _require_ok(_run(stub_state, workspace=str(workspace), extra_env=_mac_env_default(stub_state)))
    inv = invocations(stub_state)

    assert inv.count("orb start") == 1, f"OrbStack not started exactly once: {inv}"
    start_at = inv.index("orb start")
    assert all(not l.startswith(("orb create", "orb config set")) for l in inv[:start_at]), (
        f"machine work happened before OrbStack started: {inv}"
    )


def test_stale_mount_is_reconciled_with_restart(stub_state):
    # A machine that exists with the wrong (or a stale) mount: reconcile it, restart
    # once — but do not recreate.
    seed_state(stub_state, extra={"machine.agents": "1", "machine.agents.mounts": "/old/path:/workspace"})
    workspace = stub_state.parent / "agent_workspaces"

    _require_ok(_run(stub_state, workspace=str(workspace), extra_env=_mac_env_default(stub_state)))
    inv = invocations(stub_state)

    assert not any(l.startswith("orb create") for l in inv), f"existing machine recreated: {inv}"
    assert inv.count(f"orb config set machine.agents.mounts {workspace}:/workspace") == 1, (
        f"mount not reconciled: {inv}"
    )
    assert inv.count("orb restart agents") == 1, f"restart after mount change: {inv}"


def test_correct_mount_is_left_alone(stub_state):
    # An existing machine whose mount already matches: no reconciliation, no restart.
    # (The global ceilings are still reconciled — they start unset in the stub state.)
    workspace = stub_state.parent / "agent_workspaces"
    seed_state(
        stub_state, extra={"machine.agents": "1", f"machine.agents.mounts": f"{workspace}:/workspace"}
    )

    _require_ok(_run(stub_state, workspace=str(workspace), extra_env=_mac_env_default(stub_state)))
    inv = invocations(stub_state)

    assert not any(l.startswith("orb create") for l in inv), f"existing machine recreated: {inv}"
    assert not any(l.startswith("orb config set machine.agents.mounts") for l in inv), (
        f"correct mount changed: {inv}"
    )
    assert not any(l.startswith("orb restart") for l in inv), f"unnecessary restart: {inv}"


def test_missing_secrets_file_fails_with_hint(stub_state):
    result = _run(stub_state, secrets_path="playbooks/secrets/definitely-missing.yml")

    assert result.returncode != 0, f"run succeeded without a secrets file:\n{result.stdout}"
    assert "definitely-missing.yml" in result.stdout, f"path not named: {result.stdout}"
    assert "secrets.example" in result.stdout or ".example" in result.stdout, (
        f"no pointer to the template: {result.stdout}"
    )


def test_unfilled_template_parses_and_names_the_missing_secret(stub_state):
    """The committed .example is what users copy: it must load as YAML (an unquoted
    `***` placeholder once made include_vars die with a YAML alias error) and, left
    unfilled, fail on the required-secrets check rather than anywhere earlier."""
    template = REPO_ROOT / "playbooks" / "secrets" / "agents-vm-secrets.example.yml"

    result = _run(stub_state, secrets_path=str(template))

    assert result.returncode != 0, f"unfilled template provisioned:\n{result.stdout}"
    assert "YAML parsing failed" not in result.stdout, f"template is not valid YAML:\n{result.stdout}"
    assert "hermes_dashboard_password" in result.stdout, f"missing key not named: {result.stdout}"


def test_missing_required_secret_fails_with_key_named(stub_state):
    secrets = _write_secrets(stub_state, anthropic_api_key="")

    result = _run(stub_state, secrets_path=secrets)

    assert result.returncode != 0, f"run succeeded with an empty required secret:\n{result.stdout}"
    assert "anthropic_api_key" in result.stdout, f"missing key not named: {result.stdout}"


def test_optional_secrets_may_be_empty(stub_state):
    # Only the two required keys are filled in; everything else (Telegram, Google,
    # GitHub, oMLX key) stays empty and the run must still succeed — each optional
    # secret merely enables its feature when present.
    secrets = _write_secrets(stub_state)

    result = _run(stub_state, secrets_path=secrets, extra_env=_mac_env_default(stub_state))

    assert result.returncode == 0, f"optional secrets must not block provisioning:\n{result.stdout}"


def test_orb_not_installed_fails_with_hint(stub_state):
    result = _run(
        stub_state, extra_vars=("orb_bin=definitely-not-installed",),
        extra_env={"APPS_DIR": _empty_apps_dir(stub_state)},  # host /Applications must not leak in
    )

    assert result.returncode != 0, f"run succeeded without the orb CLI:\n{result.stdout}"
    assert "OrbStack" in result.stdout, f"no install hint: {result.stdout}"


# ---- OrbStack itself: installed/updated by this role on opt-in (ADR-0001 rules) ----
#
# The install path needs a PATH with no `orb` at all (a symlink farm of every other
# stub) plus an empty APPS_DIR; 'brew install --cask orbstack' plants a working CLI
# in installed-bin/ (the brew stub emulates the cask's postinstall), which _mac_install_env
# puts on PATH so later steps find it.

def test_fresh_mac_installs_orbstack_then_creates_vm(stub_state):
    workspace = stub_state.parent / "agent_workspaces"

    _require_ok(_run(stub_state, workspace=str(workspace), extra_env=_mac_install_env(stub_state)))
    inv = invocations(stub_state)

    assert inv.count("brew install --cask orbstack") == 1, f"OrbStack not installed exactly once: {inv}"
    assert inv.index("brew install --cask orbstack") < inv.index("orb list"), (
        f"machine work happened before the install: {inv}"
    )
    assert not [l for l in inv if "brew upgrade" in l and "orbstack" in l], f"install path upgraded: {inv}"
    assert any(l.startswith("orb create --isolated") for l in inv), f"VM not created after install: {inv}"


def test_brew_managed_outdated_orbstack_is_upgraded_once(stub_state):
    # Already brew-managed and outdated (the routine re-run on an existing machine):
    # one scoped upgrade, no install — and a second run must be quiet.
    seed_state(stub_state, casks=["orbstack"], extra={"cask.orbstack.outdated": "1"})
    workspace = stub_state.parent / "agent_workspaces"

    _require_ok(_run(stub_state, workspace=str(workspace),
                     extra_env={"APPS_DIR": _empty_apps_dir(stub_state)}))
    inv = invocations(stub_state)

    assert not [l for l in inv if "brew install" in l and "orbstack" in l], f"present cask reinstalled: {inv}"
    assert inv.count("brew upgrade --cask orbstack") == 1, f"outdated cask not upgraded exactly once: {inv}"
    assert inv.index("brew upgrade --cask orbstack") < inv.index("orb list"), (
        f"machine work happened before the upgrade: {inv}"
    )

    baseline = len(inv)
    _require_ok(_run(stub_state, workspace=str(workspace),
                     extra_env={"APPS_DIR": _empty_apps_dir(stub_state)}))
    new = invocations(stub_state)[baseline:]

    # The re-run still reads (brew list/outdated) — but never installs or upgrades.
    assert not [l for l in new if "orbstack" in l and ("brew install" in l or "brew upgrade" in l)], (
        f"up-to-date re-run touched the cask: {new}"
    )


def test_brew_managed_current_orbstack_is_left_alone(stub_state):
    # brew-managed and current: the role may check (brew list/outdated are reads) but
    # must not install or upgrade.
    seed_state(stub_state, casks=["orbstack"])

    _require_ok(_run(stub_state, extra_env={"APPS_DIR": _empty_apps_dir(stub_state)}))
    inv = invocations(stub_state)

    assert not [l for l in inv if "orbstack" in l and ("brew install" in l or "brew upgrade" in l)], (
        f"current cask was touched: {inv}"
    )


def test_manual_orbstack_is_left_alone(stub_state):
    # Present (CLI on PATH via the stub) but no brew record = a manual install:
    # ADR-0001 leaves it entirely alone — no install, no upgrade.
    _require_ok(_run(stub_state, extra_env=_mac_env_default(stub_state)))
    inv = invocations(stub_state)

    assert not [l for l in inv if "orbstack" in l and ("brew install" in l or "brew upgrade" in l)], (
        f"manual OrbStack was touched: {inv}"
    )


def test_orb_cli_still_missing_after_install_fails_with_hint(stub_state):
    # The install ran but the CLI still is not on PATH (a manual app-bundle whose
    # postinstall never linked it, or a broken cask install): fail with the hint,
    # before any machine work. installed-bin is NOT on PATH here, so the planted CLI
    # stays invisible — exactly like a real machine where `orb` was never linked.
    result = _run(stub_state, extra_env=_mac_install_env(stub_state, installed_bin=False))

    assert result.returncode != 0, f"run succeeded although the CLI is still missing:\n{result.stdout}"
    assert "orbstack" in result.stdout, f"no hint naming the cask: {result.stdout}"
    inv = invocations(stub_state)

    assert inv.count("brew install --cask orbstack") == 1, f"install not attempted: {inv}"
    assert not [l for l in inv if l.startswith("orb ")], (
        f"machine work happened without a usable CLI: {inv}"
    )


def test_missing_secrets_file_fails_before_any_brew_call(stub_state):
    # The secrets pre-flight in agents-vm-mac.yml runs before the role: a missing
    # file must stop the run with zero brew calls (nothing gets installed).
    result = _run(stub_state, secrets_path="playbooks/secrets/definitely-missing.yml",
                  extra_env=_mac_install_env(stub_state))

    assert result.returncode != 0, f"run succeeded without a secrets file:\n{result.stdout}"
    inv = invocations(stub_state)

    assert not [l for l in inv if "brew" in l], f"brew was called before the secrets check: {inv}"


def test_vm_host_is_reached_through_orbstack_ssh_port_as_the_mac_user(stub_state):
    # Regression: the VM host used OrbStack's `orb` SSH alias, which only resolves when
    # OrbStack has added its Include to ~/.ssh/config — on a fresh install it had not,
    # so the Linux half died with "Could not resolve hostname orb". It also assumed the
    # VM user was the machine name, but OrbStack logs in as the macOS user. The host
    # must use OrbStack's SSH server directly (127.0.0.1:32222 + its own key and
    # known_hosts), with the explicit <user>@<machine> login.
    import json

    out = stub_state.parent / "vm-hostvars.json"
    wrapper = stub_state.parent / "dump-vm-hostvars.yml"
    wrapper.write_text(
        f"- import_playbook: {MAC_PLAYBOOK}\n"
        "- hosts: localhost\n"
        "  connection: local\n"
        "  gather_facts: false\n"
        "  vars_files: [" + str(REPO_ROOT / "playbooks" / "vars_agents_vm.yml") + "]\n"
        "  tasks:\n"
        "    - ansible.builtin.copy:\n"
        f"        dest: {out}\n"
        "        content: >-\n"
        "          {{ {'host': hostvars[agents_vm_name].ansible_host,\n"
        "              'port': hostvars[agents_vm_name].ansible_port,\n"
        "              'user': hostvars[agents_vm_name].ansible_user,\n"
        "              'key': hostvars[agents_vm_name].ansible_ssh_private_key_file,\n"
        "              'args': hostvars[agents_vm_name].ansible_ssh_common_args,\n"
        "              'remote_tmp': hostvars[agents_vm_name].ansible_remote_tmp,\n"
        "              'vm_user': agents_vm_user, 'vm_home': agents_vm_home} | to_json }}\n",
        encoding="utf-8",
    )
    env = _mac_env_default(stub_state)
    env["USER"] = "macuser"
    _require_ok(run_playbook(
        wrapper, stub_state, seed_skills=False, extra_env=env,
        extra_vars=(f"agents_vm_secrets_file={_write_secrets(stub_state)}",),
    ))

    got = json.loads(out.read_text(encoding="utf-8"))
    orb_ssh = stub_state.parent / "home" / ".orbstack" / "ssh"
    assert got["host"] == "127.0.0.1", got
    assert int(got["port"]) == 32222, got
    assert got["user"] == "macuser@agents", got
    assert got["key"] == f"{orb_ssh}/id_ed25519", got
    assert f"UserKnownHostsFile={orb_ssh}/known_hosts" in got["args"], got
    assert got["vm_user"] == "macuser", got
    assert got["vm_home"] == "/home/macuser", got
    # Ansible expands remote_tmp's ~ as ~<ansible_user>, and no Linux user is called
    # "macuser@agents" — so the default left a literal ~macuser@agents/.ansible/tmp
    # directory in the VM user's home. Pin it to an absolute path instead.
    assert got["remote_tmp"] == "/home/macuser/.ansible/tmp", got


# ---- play 2 (VM side): run on localhost with tmp paths and stubs ----------------
#
# Play 2 targets the VM host; under test we name it "localhost" so it maps onto the
# inventory, point every path at tmp dirs (agents_vm_home/root/workspace), disable
# become and serve the installer scripts from file:// stand-ins. Assertions then read
# real files (configs, units) out of those tmp dirs plus the stub invocation log.



def _fake_installer(stub_state, name, body):
    """A stand-in installer script served via file://; records its args + HOME."""
    record = stub_state / f"{name}-installer"
    path = stub_state.parent / f"fake-{name}.sh"
    path.write_text(
        "#!/bin/sh\n"
        f"printf 'args=%s\\nHOME=%s\\n' \"$*\" \"${{HOME}}\" >> '{record}'\n" + body,
        encoding="utf-8",
    )
    path.chmod(0o755)
    return f"file://{path}"


HERMES_INSTALLER_BODY = (
    'mkdir -p "${HERMES_HOME}/hermes-agent"\n'
    "mkdir -p \"$HOME/.local/bin\"\n"
    'printf \'#!/bin/sh\\n# stub hermes wrapper\\n\' >"$HOME/.local/bin/hermes"\n'
    "chmod +x \"$HOME/.local/bin/hermes\"\n"
)

OPENCODE_INSTALLER_BODY = (
    "mkdir -p \"$HOME/.opencode/bin\"\n"
    'printf \'#!/bin/sh\\n# stub opencode binary\\n\' >"$HOME/.opencode/bin/opencode"\n'
    "chmod +x \"$HOME/.opencode/bin/opencode\"\n"
)

CLAUDE_INSTALLER_BODY = (
    "mkdir -p \"$HOME/.local/bin\"\n"
    'printf \'#!/bin/sh\\n# stub claude binary\\n\' >"$HOME/.local/bin/claude"\n'
    "chmod +x \"$HOME/.local/bin/claude\"\n"
)

# The fake `uv` binary doubles as the stub for these tests: it records its calls in
# the shared invocation log (same format as tests/stubs/*) and implements `uv tool
# install <pkg>` the way real uv does (entry-point binary under $HOME/.local/bin).
# It cannot live in STUBS_DIR itself: a file named `uv` there would be found by
# site.yml's formula-presence check (command -v uv) in the M3 tests.
UV_INSTALLER_BODY = '''mkdir -p "$HOME/.local/bin"
cat >"$HOME/.local/bin/uv" <<'FAKE_UV'
#!/bin/sh
if [ -n "${STUB_STATE_DIR:-}" ]; then printf 'uv %s\\n' "$*" >>"$STUB_STATE_DIR/invocations.log"; fi
if [ "${1:-} ${2:-}" != "tool install" ]; then echo "stub uv: unhandled invocation: $*" >&2; exit 1; fi
pkg="${3:-}"
[ -n "$pkg" ] || { echo "stub uv: tool install needs a package" >&2; exit 1; }
home="${HOME:?stub uv requires HOME}"
mkdir -p "$home/.local/bin"
printf '#!/bin/sh\\n# stub uv tool binary for %s\\n' "$pkg" >"$home/.local/bin/$pkg"
chmod +x "$home/.local/bin/$pkg"
FAKE_UV
chmod +x "$HOME/.local/bin/uv"
'''


def _gh_shim(stub_state):
    """A per-test `gh` on PATH, delegating to the gh stub logic in tests/stubs/_gh.sh.

    The real logic cannot live at STUBS_DIR/gh: a file named `gh` there would be found
    by site.yml's formula-presence check (command -v gh) in the M3 tests, classifying
    brew's `gh` formula as manually installed. Only VM-side runs (this file) need gh.
    """
    extra_bin = stub_state.parent / "extra-bin"
    extra_bin.mkdir(exist_ok=True)
    shim = extra_bin / "gh"
    shim.write_text(f'#!/bin/sh\nexec {REPO_ROOT}/tests/stubs/_gh.sh "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    return extra_bin


def _run_vm(stub_state, secrets_path=None, extra_vars=(), with_installers=True):
    """Run the whole playbook; play 2 lands on localhost against tmp dirs + stubs."""
    home = stub_state.parent / "vm-home"
    root = stub_state.parent / "vm-root"
    guest_ws = stub_state.parent / "vm-workspace"
    host_ws = stub_state.parent / "agent_workspaces"
    if secrets_path is None:
        secrets_path = _write_secrets(stub_state)
    vars_ = [
        f"agents_vm_secrets_file={secrets_path}",
        "agents_vm_name=localhost",   # play 2 targets the inventory host → runs locally
        f"agents_vm_home={home}",
        f"agents_vm_root={root}",
        f"agents_vm_workspace_host_path={host_ws}",
        f"agents_vm_workspace_guest_path={guest_ws}",
        "ansible_become=false",       # never escalate under test (all paths are tmp anyway)
        "ansible_connection=local",   # the VM host is mapped onto localhost under test
        f"ansible_python_interpreter={venv_bin() / 'python'}",
    ]
    if with_installers:
        vars_ += [
            f"hermes_install_url={_fake_installer(stub_state, 'hermes', HERMES_INSTALLER_BODY)}",
            f"opencode_install_url={_fake_installer(stub_state, 'opencode', OPENCODE_INSTALLER_BODY)}",
            f"uv_install_url={_fake_installer(stub_state, 'uv', UV_INSTALLER_BODY)}",
            f"claude_install_url={_fake_installer(stub_state, 'claude', CLAUDE_INSTALLER_BODY)}",
        ]
    path = (
        f"{_gh_shim(stub_state)}{os.pathsep}{STUBS_DIR}{os.pathsep}"
        f"{venv_bin()}{os.pathsep}{os.environ['PATH']}"
    )
    return run_playbook(
        LINUX_PLAYBOOK, stub_state, extra_vars=tuple(vars_) + tuple(extra_vars),
        seed_skills=False, extra_env={"PATH": path},
    )


def _full_secrets(stub_state):
    """Everything filled in: both agents get Anthropic + oMLX, plus Telegram/Google/GitHub."""
    return _write_secrets(
        stub_state,
        telegram_bot_token="123456:STUB-BOT",
        telegram_allowed_users="424242",
        google_oauth_client_id="stub-client-id.apps.googleusercontent.com",
        google_oauth_client_secret="stub-client-secret",
        github_token="github_pat_stub",
        local_llm_api_key="omlx-key",
    )


# ---- playbooks/agents-vm.yml (the parent, what bootstrap actually runs) ----------


def test_parent_playbook_imports_resolve_and_both_halves_run(stub_state):
    # Regression: import_playbook paths resolve against the IMPORTING playbook's
    # directory, so they must be sibling-relative. The old `playbooks/...` form
    # made Ansible look for playbooks/playbooks/*.yml — which the stubs never
    # caught, because they run each half directly (and M2 records args only).
    home = stub_state.parent / "vm-home"
    root = stub_state.parent / "vm-root"
    guest_ws = stub_state.parent / "vm-workspace"
    host_ws = stub_state.parent / "agent_workspaces"

    result = run_playbook(
        PARENT_PLAYBOOK, stub_state, seed_skills=False,
        extra_vars=(
            f"agents_vm_secrets_file={_write_secrets(stub_state)}",
            "agents_vm_name=localhost",   # play 2 targets the inventory host locally
            f"agents_vm_home={home}",
            f"agents_vm_root={root}",
            f"agents_vm_workspace_host_path={host_ws}",
            f"agents_vm_workspace_guest_path={guest_ws}",
            "ansible_become=false",       # never escalate under test (all paths are tmp)
            "ansible_connection=local",   # the VM host is mapped onto localhost under test
            f"ansible_python_interpreter={venv_bin() / 'python'}",
            # file:// stand-ins for the installer scripts (see _run_vm)
            f"hermes_install_url={_fake_installer(stub_state, 'hermes', HERMES_INSTALLER_BODY)}",
            f"opencode_install_url={_fake_installer(stub_state, 'opencode', OPENCODE_INSTALLER_BODY)}",
            f"uv_install_url={_fake_installer(stub_state, 'uv', UV_INSTALLER_BODY)}",
            f"claude_install_url={_fake_installer(stub_state, 'claude', CLAUDE_INSTALLER_BODY)}",
        ),
        extra_env={
            "PATH": (f"{_gh_shim(stub_state)}{os.pathsep}{STUBS_DIR}{os.pathsep}"
                     f"{venv_bin()}{os.pathsep}{os.environ['PATH']}"),
            "APPS_DIR": _empty_apps_dir(stub_state),   # host /Applications must not leak
        },
    )

    assert result.returncode == 0, (
        f"parent playbook failed:\n{result.stdout}\n{result.stderr}"
    )
    inv = invocations(stub_state)

    # Both halves really ran in one invocation: the Mac half created the machine,
    # the VM half installed its base packages.
    assert any(l.startswith("orb create --isolated") for l in inv), f"Mac half did not run: {inv}"
    assert any(l.startswith("apt-get install") for l in inv), f"VM half did not run: {inv}"


def test_vm_fresh_full_run_provisions_everything(stub_state):
    import json

    secrets = _full_secrets(stub_state)
    result = _run_vm(
        stub_state, secrets_path=secrets,
        extra_vars=('{"local_llm_models": ["qwen3-coder-480b", "gpt-oss-120b"]}',),
    )
    _require_ok(result)

    home = stub_state.parent / "vm-home"
    root = stub_state.parent / "vm-root"
    ws = stub_state.parent / "vm-workspace"
    inv = invocations(stub_state)

    # base: one apt pass with every package (the final list is recorded in the plan's
    # deviations); uv present
    assert len([l for l in inv if l.startswith("apt-get install")]) == 1
    apt = [l for l in inv if l.startswith("apt-get install")][0]
    for pkg in ("git", "curl", "jq", "ca-certificates", "python3-venv",
                "nodejs", "unzip", "build-essential"):
        assert pkg in apt, f"{pkg} missing from the apt call: {apt}"
    # Node.js comes from NodeSource (Ubuntu's 18 is too old for the skills CLI), and
    # Ubuntu's npm package conflicts with it
    assert " npm" not in apt, f"Ubuntu npm must not be installed: {apt}"
    repo = (root / "etc/apt/sources.list.d/nodesource.list").read_text(encoding="utf-8")
    assert "deb.nodesource.com/node_24.x" in repo, f"NodeSource repo: {repo}"
    assert (root / "etc/apt/keyrings/nodesource.asc").is_file(), "NodeSource key missing"

    # GitHub access
    assert inv.count("gh auth login --with-token --hostname github.com") == 1, f"login: {inv}"
    assert inv.count("gh auth setup-git") == 1, f"setup-git: {inv}"
    assert (home / ".gitconfig").is_file(), "git identity not written"
    for repo_dir in ("mac-setup", "health-tracker"):
        assert (ws / repo_dir / ".git").is_dir(), f"{repo_dir} not cloned"

    # OpenCode: env + config + unit
    env_file = (home / ".config/opencode/env").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-stub" in env_file, f"env file: {env_file}"
    assert "OMLX_API_KEY=omlx-key" in env_file, f"env file: {env_file}"
    assert (home / ".config/opencode/env").stat().st_mode & 0o777 == 0o600, "env file not 0600"
    oc = json.loads((home / ".config/opencode/opencode.json").read_text(encoding="utf-8"))
    assert oc["server"] == {"hostname": "127.0.0.1", "port": 4096}, f"server: {oc['server']}"
    assert oc["model"] == "anthropic/claude-sonnet-4-5", f"default model: {oc['model']}"
    assert oc["provider"]["anthropic"]["options"]["apiKey"] == "{env:ANTHROPIC_API_KEY}"
    omlx = oc["provider"]["omlx"]
    assert set(omlx["models"]) == {"qwen3-coder-480b", "gpt-oss-120b"}, f"omlx models: {omlx}"
    assert omlx["options"]["baseURL"] == "http://llm.internal:8000/v1"
    assert omlx["options"]["apiKey"] == "{env:OMLX_API_KEY}"

    # services
    assert inv.count("systemctl enable --now opencode-server") == 1, f"enable: {inv}"
    unit = (root / "etc/systemd/system/opencode-server.service").read_text(encoding="utf-8")
    assert ".opencode/bin/opencode serve" in unit and "EnvironmentFile=" + str(home / ".config/opencode/env") in unit

    # Hermes: .env, config.yaml, bridge skill, both units
    hermes_env = (home / ".hermes/.env").read_text(encoding="utf-8")
    for line in (
        "ANTHROPIC_API_KEY=sk-ant-stub",
        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin",
        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=stub-password",
    ):
        assert line in hermes_env, f"{line} missing from .env:\n{hermes_env}"
    assert "TELEGRAM_BOT_TOKEN=123456:STUB-BOT" in hermes_env, f".env:\n{hermes_env}"
    assert "TELEGRAM_ALLOWED_USERS=424242" in hermes_env, f".env:\n{hermes_env}"
    secret = [l.split("=", 1)[1] for l in hermes_env.splitlines()
              if l.startswith("HERMES_DASHBOARD_BASIC_AUTH_SECRET=")][0]
    assert len(secret) >= 32, f"signing secret too short: {secret!r}"
    assert (home / ".hermes/.env").stat().st_mode & 0o777 == 0o600, ".env not 0600"

    import yaml
    cfg = yaml.safe_load((home / ".hermes/config.yaml").read_text(encoding="utf-8"))
    assert cfg["model"] == {"provider": "anthropic", "default": "claude-sonnet-4-6"}, f"model: {cfg['model']}"
    assert cfg["approvals"] == {"mode": "smart"}, f"approvals: {cfg['approvals']}"
    assert cfg["providers"]["omlx"]["api"] == "http://llm.internal:8000/v1"
    assert cfg["providers"]["omlx"]["key_env"] == "OMLX_API_KEY"
    mcp = cfg["mcp_servers"]["google_workspace"]
    assert str(mcp["command"]).endswith("/.local/bin/workspace-mcp"), f"mcp command: {mcp}"
    assert "--read-only" in mcp["args"] and "gmail" in mcp["args"] and "calendar" in mcp["args"], f"mcp args: {mcp}"
    assert mcp["env"]["GOOGLE_OAUTH_CLIENT_ID"] == "stub-client-id.apps.googleusercontent.com"
    assert mcp["env"]["GOOGLE_OAUTH_CLIENT_SECRET"] == "stub-client-secret"

    skill = home / ".hermes/skills/opencode-bridge/SKILL.md"
    assert skill.is_file(), "opencode-bridge skill not written"
    body = skill.read_text(encoding="utf-8")
    assert "opencode run --server http://127.0.0.1:4096" in body, f"skill: {body}"

    for svc in ("hermes-dashboard", "hermes-gateway"):
        assert (root / f"etc/systemd/system/{svc}.service").is_file(), f"{svc} unit missing"
        assert inv.count(f"systemctl enable --now {svc}") == 1, f"{svc} not enabled: {inv}"
    dash = (root / "etc/systemd/system/hermes-dashboard.service").read_text(encoding="utf-8")
    assert "--host 0.0.0.0 --port 9119" in dash and "--no-open" in dash, f"dashboard unit: {dash}"

    # Claude Code (native installer) and Codex (npm, user prefix ~/.local) for the VM user
    assert (home / ".local/bin/claude").is_file(), "Claude Code not installed"
    assert (stub_state / "claude-installer").read_text().count(f"HOME={home}") == 1, (
        "Claude Code installer not run exactly once as the VM user"
    )
    assert inv.count("npm install -g @openai/codex") == 1, f"codex: {inv}"
    assert (home / ".local/bin/codex").is_file(), "Codex not installed"
    assert f"prefix={home}/.local" in (home / ".npmrc").read_text(encoding="utf-8")
    # ...neither is signed in yet, so the run says how
    assert "claude (then /login)" in result.stdout and "codex login --device-auth" in result.stdout, (
        f"no sign-in reminder for the CLIs:\n{result.stdout}"
    )

    # Matt skills for the VM user, same targets as the Mac (OpenCode reads ~/.agents/skills)
    assert inv.count(
        "npx -y skills@latest add mattpocock/skills --global --skill * --agent codex --agent claude-code --yes"
    ) == 1, f"VM skills install: {[l for l in inv if l.startswith('npx')]}"
    assert (home / ".claude/skills/setup-matt-pocock-skills/SKILL.md").is_file(), "Claude Code skills missing"

    # workspace-mcp tool (for the mcp_servers entry)
    assert inv.count("uv tool install workspace-mcp") == 1, f"workspace-mcp: {inv}"
    assert (home / ".local/bin/workspace-mcp").is_file()

    # Post-run reminder: with a Google client configured, the inboxes that still need
    # their one-time browser sign-in are named (gmail_accounts, rollout order).
    for acct in GMAIL_ACCOUNTS:   # loaded from vars_agents_vm.yml — no test-owned copy
        assert acct in result.stdout, f"post-run reminder missing {acct}:\n{result.stdout}"


def test_vm_rerun_is_quiet(stub_state):
    secrets = _full_secrets(stub_state)

    result1 = _run_vm(stub_state, secrets_path=secrets, extra_vars=('{"local_llm_models": ["qwen3-coder-480b"]}',))
    _require_ok(result1)

    home = stub_state.parent / "vm-home"
    secret_before = [l for l in (home / ".hermes/.env").read_text().splitlines()
                     if l.startswith("HERMES_DASHBOARD_BASIC_AUTH_SECRET=")][0]
    clones_before = [l for l in invocations(stub_state) if l.startswith("git clone")]
    baseline = len(invocations(stub_state))

    result2 = _run_vm(stub_state, secrets_path=secrets, extra_vars=('{"local_llm_models": ["qwen3-coder-480b"]}',))
    _require_ok(result2)

    new = invocations(stub_state)[baseline:]
    assert not any(l.startswith("git clone") for l in new), f"repos re-cloned: {new}"
    assert len(clones_before) == 2, f"expected exactly two clones on the fresh run: {clones_before}"
    assert not any(l.startswith("gh auth login") for l in new), f"re-login on re-run: {new}"
    assert not any(l.startswith("uv tool install") for l in new), f"workspace-mcp reinstalled: {new}"
    assert not any(l.startswith("npm install") for l in new), f"codex reinstalled: {new}"
    assert not any(l.startswith("npx") and " add " in l for l in new), f"skills reinstalled: {new}"
    assert (stub_state / "claude-installer").read_text().count("args=") == 1, "Claude Code reinstalled"
    assert not any(l.startswith("orb create") for l in new), f"machine recreated: {new}"
    assert not any(l.startswith("systemctl enable") for l in new), f"services re-enabled: {new}"
    assert not any(l.startswith("systemctl restart") for l in new), f"services restarted: {new}"
    # the dashboard signing secret must be stable across runs (sessions would die otherwise)
    secret_after = [l for l in (home / ".hermes/.env").read_text().splitlines()
                    if l.startswith("HERMES_DASHBOARD_BASIC_AUTH_SECRET=")][0]
    assert secret_before == secret_after, f"signing secret rotated on re-run: {secret_before!r} -> {secret_after!r}"


def test_vm_without_optional_secrets_skips_their_features(stub_state):
    import json

    # Only the two required keys: no Telegram, Google, GitHub or oMLX key.
    secrets = _write_secrets(stub_state)

    result = _run_vm(stub_state, secrets_path=secrets)
    _require_ok(result)

    home = stub_state.parent / "vm-home"
    root = stub_state.parent / "vm-root"
    inv = invocations(stub_state)

    assert not (root / "etc/systemd/system/hermes-gateway.service").exists(), (
        f"gateway unit created without a bot token: {inv}"
    )
    assert not any(l.startswith("systemctl") and "hermes-gateway" in l for l in inv), f"gateway touched: {inv}"

    hermes_env = (home / ".hermes/.env").read_text(encoding="utf-8")
    assert "TELEGRAM" not in hermes_env, f".env gained telegram keys: {hermes_env}"

    import yaml
    cfg = yaml.safe_load((home / ".hermes/config.yaml").read_text(encoding="utf-8"))
    assert "mcp_servers" not in cfg, f"google MCP registered without credentials: {cfg}"
    assert "providers" not in cfg, f"omlx provider without model IDs: {cfg}"

    oc = json.loads((home / ".config/opencode/opencode.json").read_text(encoding="utf-8"))
    assert "omlx" not in oc["provider"], f"omlx provider without model IDs: {oc['provider']}"
    env_file = (home / ".config/opencode/env").read_text(encoding="utf-8")
    assert "OMLX_API_KEY" not in env_file, f"env file: {env_file}"

    assert not any(l.startswith("gh auth login") for l in inv), f"login without a token: {inv}"
    assert not any(l.startswith("git clone") for l in inv), f"clones without a token: {inv}"
    # ...and says so: an empty /workspace with no word in the run output reads as a
    # broken mount.
    assert "github_token" in result.stdout and "/workspace" in result.stdout, (
        f"no notice that repo clones were skipped: {result.stdout}"
    )

    assert GMAIL_ACCOUNTS[0] not in result.stdout, (
        f"sign-in reminder shown without a Google client: {result.stdout}"
    )


def test_vm_with_omlx_models_but_no_key(stub_state):
    import json

    secrets = _full_secrets(stub_state)  # includes local_llm_api_key — unset it again below
    result = _run_vm(
        stub_state, secrets_path=secrets,
        extra_vars=('{"local_llm_models": ["qwen3-coder-480b"]}', "local_llm_api_key="),
    )
    _require_ok(result)

    home = stub_state.parent / "vm-home"
    oc = json.loads((home / ".config/opencode/opencode.json").read_text(encoding="utf-8"))
    omlx = oc["provider"]["omlx"]
    assert set(omlx["models"]) == {"qwen3-coder-480b"}, f"omlx models: {omlx}"
    assert "apiKey" not in omlx["options"], f"no key configured, yet one was referenced: {omlx}"
    env_file = (home / ".config/opencode/env").read_text(encoding="utf-8")
    assert "OMLX_API_KEY" not in env_file, f"env file: {env_file}"

    import yaml
    cfg = yaml.safe_load((home / ".hermes/config.yaml").read_text(encoding="utf-8"))
    assert "key_env" not in cfg["providers"]["omlx"], f"no key configured, yet one was referenced: {cfg}"


def test_vm_signed_in_clis_get_no_reminder(stub_state):
    # Credentials already in place (signed in by hand after an earlier run): no reminder.
    home = stub_state.parent / "vm-home"
    for cred in (".claude/.credentials.json", ".codex/auth.json"):
        (home / cred).parent.mkdir(parents=True, exist_ok=True)
        (home / cred).write_text("{}", encoding="utf-8")

    result = _run_vm(stub_state)
    _require_ok(result)

    assert "codex login" not in result.stdout and "/login" not in result.stdout, (
        f"sign-in reminder although both CLIs are signed in:\n{result.stdout}"
    )
