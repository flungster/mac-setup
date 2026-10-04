"""M5: playbooks/agents-vm.yml against the stubs.

The playbook provisions the agents VM in two halves: play 1 runs on this Mac
(OrbStack ceilings + the isolated machine), and later plays reach into the VM
through OrbStack's SSH alias. This file tests what can be tested offline: play 1
end-to-end against the `orb` stub, and — once each VM-side play lands here too —
those runs with the "remote" host mapped back onto localhost, every path pointed at
tmp dirs (agents_vm_home/agents_vm_root overrides) and all CLI calls stubbed.

The secrets file is a plain (unencrypted) YAML in tests, passed via
-e agents_vm_secrets_file=...: the playbook treats vaulted and plain files alike.

Nothing real is installed or created outside tmp dirs: the `orb` stub records
every call in invocations.log and keeps machine/config state in state.env.
"""
from conftest import REPO_ROOT, invocations, run_playbook, seed_state

PLAYBOOK = REPO_ROOT / "playbooks" / "agents-vm.yml"


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


def _run(stub_state, secrets_path=None, workspace=None, extra_vars=()):
    if secrets_path is None:
        secrets_path = _write_secrets(stub_state)
    vars_ = [f"agents_vm_secrets_file={secrets_path}"]
    if workspace is not None:
        vars_.append(f"agents_vm_workspace_host_path={workspace}")
    return run_playbook(
        PLAYBOOK, stub_state, extra_vars=tuple(vars_) + tuple(extra_vars), seed_skills=False
    )


def _require_ok(result):
    assert result.returncode == 0, f"playbook failed:\n{result.stdout}"


def test_fresh_run_creates_the_vm_and_sets_ceilings(stub_state):
    workspace = stub_state.parent / "agent_workspaces"

    _require_ok(_run(stub_state, workspace=str(workspace)))
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

    _require_ok(_run(stub_state, workspace=str(workspace)))
    baseline = len(invocations(stub_state))

    _require_ok(_run(stub_state, workspace=str(workspace)))
    new = invocations(stub_state)[baseline:]

    assert not any(l.startswith("orb create") for l in new), f"machine recreated: {new}"
    assert not any(l.startswith("orb config set") for l in new), f"re-run changed settings: {new}"
    assert not any(l.startswith("orb restart") for l in new), f"re-run restarted the VM: {new}"


def test_stopped_orbstack_is_started_first(stub_state):
    seed_state(stub_state, extra={"orb.stopped": 1})
    workspace = stub_state.parent / "agent_workspaces"

    _require_ok(_run(stub_state, workspace=str(workspace)))
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

    _require_ok(_run(stub_state, workspace=str(workspace)))
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

    _require_ok(_run(stub_state, workspace=str(workspace)))
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

    result = _run(stub_state, secrets_path=secrets)

    assert result.returncode == 0, f"optional secrets must not block provisioning:\n{result.stdout}"


def test_orb_not_installed_fails_with_hint(stub_state):
    result = _run(stub_state, extra_vars=("orb_bin=definitely-not-installed",))

    assert result.returncode != 0, f"run succeeded without the orb CLI:\n{result.stdout}"
    assert "OrbStack" in result.stdout, f"no install hint: {result.stdout}"
