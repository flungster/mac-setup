"""M4: scripts/verify.sh against a temporary HOME and fake command-line tools.

This is the offline half of `make verify`: it pins pass/fail behavior without
installing anything real. The human runs the actual script on a provisioned Mac.
"""
import os
import subprocess

from conftest import REPO_ROOT, seed_managed_matt_skills

VERIFY = REPO_ROOT / "scripts" / "verify.sh"


def _fake_bin(tmp_path, names=()):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    for name in names:
        exe = d / name
        if not exe.exists():
            exe.write_text("#!/bin/sh\necho '0.1 (fake)'\n", encoding="utf-8")
        exe.chmod(0o755)
    return d


def _run_verify(tmp_path, home, present_commands=()):
    fake = _fake_bin(tmp_path, present_commands)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = f"{fake}{os.pathsep}/usr/bin{os.pathsep}/bin"
    return subprocess.run(
        ["bash", str(VERIFY)], capture_output=True, text=True, env=env, timeout=60
    )


def test_verify_passes_when_commands_and_skills_are_present(tmp_path):
    home = tmp_path / "home"
    seed_managed_matt_skills(home)

    result = _run_verify(tmp_path, home, ("claude", "codex", "node"))

    assert result.returncode == 0, f"verify failed:\n{result.stdout}\n{result.stderr}"
    assert "[verify] passed" in result.stdout, f"no pass summary:\n{result.stdout}"


def test_verify_fails_when_commands_and_skills_are_missing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    result = _run_verify(tmp_path, home)

    assert result.returncode == 1
    output = result.stdout + result.stderr
    for expected in ("claude", "codex", "node", "Matt Pocock skills"):
        assert expected in output, f"missing item not reported: {expected!r}\n{output}"


def test_verify_fails_when_skill_sets_differ(tmp_path):
    home = tmp_path / "home"
    seed_managed_matt_skills(home)
    extra = home / ".agents/skills/extra"
    extra.mkdir(parents=True)
    (extra / "SKILL.md").write_text("---\nname: extra\n---\n", encoding="utf-8")

    result = _run_verify(tmp_path, home, ("claude", "codex", "node"))

    assert result.returncode == 1
    assert "differ" in (result.stdout + result.stderr)
