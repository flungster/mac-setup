# Plan: OrbStack + agents VM behind one bootstrap question (plus code-review follow-ups)

Status: **implemented** — one commit per step below, each keeping `make check` + `make test` green (see git history). Base when the work started: HEAD `7159806` (agents VM feature complete, 56 tests green); the suite now stands at 66.

## Goal

Each bootstrap run asks one question:

    Install/update OrbStack and the agents VM (Hermes Agent + OpenCode)? [y/N]

- **Yes** → install or update OrbStack, create/reconcile the `agents` VM, provision everything inside it.
- **No** → touch nothing related: no OrbStack install or upgrade, VM neither created nor changed (an existing one is not stopped or deleted).

## Decisions (confirmed as written before implementation)

1. **Ask on every run**, even if the VM already exists (unlike the old Hermes prompt, which auto-answered yes when Hermes was already installed). The question is "install/update", so it's a choice each time.
2. **Yes but no secrets file → stop the bootstrap immediately**, before anything is installed, pointing at `playbooks/secrets/agents-vm-secrets.example.yml`.
3. **Default answer: N.** No terminal attached → N (never hang).

## Work order (each step keeps `make check` + `make test` green; one commit per step, AGENTS.md trailer)

### 0. Housekeeping
- Delete `docs/prd_automated_agent_infrastructure.md` (old two-VM design, contradicts ADR 0002).
- Update `docs/plans/agents-vm.md`: drop the "Supersedes docs/prd_…" reference to the deleted file, and record the changes below (OrbStack moved out of the baseline, prompt instead of env-only opt-in, the decisions above, resolved review findings).

### 1. Take OrbStack out of the Mac baseline — `playbooks/site.yml`
- Remove the `orbstack` cask. A default bootstrap never touches OrbStack.
- Tests: M3's inventory comes from `site.yml`, so it follows on its own. Add an M3 check that a default run never mentions orbstack.

### 2. `orbstack_vm` role installs/updates OrbStack itself (ADR-0001 rules)
New first step, after the secrets check in `agents-vm-mac.yml`, so missing/incomplete secrets stop the run before any install:
- **Not present** (no `OrbStack.app` in apps dir, no `orb` on PATH) → `brew install --cask orbstack`.
- **Brew-managed** → `brew outdated --cask orbstack`; upgrade only if outdated.
- **Installed by hand** → leave entirely alone (no install, no upgrade).
- Still no `orb` afterwards → fail with a clear message (replaces today's "it is in site.yml's cask list" hint).
- Existing steps follow unchanged: start if stopped → ceilings → create/reconcile → add_host → Linux half.
- Tests (M5 Mac side, brew stub alongside `orb` stub): fresh → install once then create VM; brew-managed outdated → one upgrade; up to date → no brew write; manual → untouched; missing secrets → zero brew calls; still-missing `orb` → clear error.

### 3. Bootstrap prompt — `bootstrap.sh`
- Replace the env-only `choose_agents_vm` with a prompt (the M11 Hermes `choose_hermes` pattern):
  - `PROVISION_AGENTS_VM=1/true/0/false` answers in advance; invalid values fail before anything runs.
  - Interactive TTY → ask the question above (default N).
  - No TTY → N, logged.
  - Asked first, before any install work.
- On yes:
  - Check the secrets file exists up front (decision 2).
  - Run `site.yml`, then `agents-vm.yml`.
  - Vault: `--vault-password-file "$AGENTS_VAULT_PASSWORD_FILE"` if set, else `--ask-vault-pass`.
  - Build the extra flag safely for bash 3.2 + `set -u` (no empty-array expansion).
- On no: run `site.yml` only; log `agents VM: skipping (OrbStack and the VM left as they are)`.
- `scripts/verify.sh`: already skips VM checks when `orb`/VM absent. Fold in review item: read machine name + ports from `playbooks/vars_agents_vm.yml` instead of hard-coding `agents`/9119/4096.
- Tests (M2):
  - Env yes → two playbooks; env no → one.
  - No TTY → one playbook, "skipping" logged.
  - Yes without a password file → `--ask-vault-pass`; with one → forwarded.
  - Yes + missing secrets file → fails before any playbook.
  - Invalid value → fails early.
  - One pseudo-terminal test typing `y` and one typing `n` to drive the real prompt.

### 4. Code-review follow-ups (folded in)
- **Gmail accounts**: add `gmail_accounts` (list of the three addresses, in rollout order) to `vars_agents_vm.yml`. Surface it where it's useful: the README sign-in instructions, and a post-run message listing the accounts still to sign in. No new behaviour beyond that. M5 asserts the var exists.
- **apt packages**: restore `unzip` and `build-essential` to `agents_vm_base_packages` (plan line 75), keep `nodejs`/`npm`/`ca-certificates` (needed by skills CLI / TLS). Update the M5 package assertion. Note the final list in the plan.
- **Repeated systemd steps** (opencode-server, hermes-dashboard, hermes-gateway): extract one shared task file (e.g. `playbooks/roles/agents_base/tasks/systemd_unit.yml` or a small `systemd_unit` role) taking `unit_name`, `unit_template`, `enabled_when`; call it 3×. Behaviour and M5 assertions unchanged.
- **Repeated OrbStack setting steps** (memory_mib, cpu, machines.expose_ports_to_lan): one looped include over `(key, value)` pairs. Invocations unchanged, so the M5 orb assertions still hold.
- **Spec wording deviations** (env file at `~/.config/opencode/env`; host/port in `opencode.json` instead of unit flags; dashboard username as a var and signing secret auto-generated rather than in the vault): record them in `docs/plans/agents-vm.md` as accepted deviations (step 0).

### 5. Docs
- **README:**
  - Replace "OrbStack is in the inventory…" with the prompt.
  - Rewrite the Agents VM "Opt-in" paragraph: interactive question; `PROVISION_AGENTS_VM` answers in advance; vault password prompt vs `AGENTS_VAULT_PASSWORD_FILE`.
  - Add a **"Rotating secrets"** subsection (review finding): edit the vault file (`ansible-vault edit`) and re-run. For the GitHub PAT, also delete `~/.config/gh` in the VM first. The dashboard signing secret is removed from `~/.hermes/.env` to rotate it. The Google client and the Telegram token are re-applied on re-run.
  - Add the `gmail_accounts` sign-in list.
- **ADR 0002:** add a consequence: OrbStack is installed or updated only on "yes", never in the Mac baseline; manual installs are left alone (ADR-0001).
- **CONTEXT.md:** "Agents VM" changes from opt-in by `PROVISION_AGENTS_VM` to opt-in by bootstrap question (env var answers it in advance).

## Out of scope
- Uninstalling OrbStack or deleting the VM on "no".
- Per-service resource limits.
