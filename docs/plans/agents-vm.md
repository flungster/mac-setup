# Plan: agents VM (Hermes Agent + OpenCode) on the Mac Studio

Status: implemented — every tracer bullet below has landed (see git history). Changes made after implementation are recorded at the end of this file and in `docs/plans/orbstack-opt-in.md`.

## Goal

One isolated Linux VM on the Mac Studio (M1 Max, 32 GB, static LAN IP) runs **Hermes Agent** (orchestrator) and **OpenCode** (coding agent), provisioned by Ansible from this repo and reachable over SSH from macOS. Hermes is used:

- from any LAN device via its web dashboard, and
- from anywhere via Telegram,

and can reach the LAN (Home Assistant, the oMLX server), read three Gmail inboxes and their calendars (read-only), and drive OpenCode against personal GitHub repos.

## Architecture

```
Mac Studio M1 Max (32 GB, static IP)
├── OrbStack  (memory ceiling 12 GB, CPU ceiling 6 cores — global, not reserved)
│   └── machine "agents"  (Ubuntu 24.04 ARM64, --isolated, no network isolation)
│       ├── /workspace  ← ~/agent_workspaces   (the ONLY Mac folder visible)
│       │     ├── mac-setup/
│       │     └── health-tracker/
│       ├── opencode-server.service       127.0.0.1:4096   (cwd /workspace)
│       ├── hermes-dashboard.service      0.0.0.0:9119     (basic-auth gate)
│       ├── hermes-gateway.service        Telegram long polling (outbound only)
│       └── google-workspace-mcp.service  127.0.0.1        (--read-only, gmail+calendar)
│
├── LAN devices  → http://<mac-ip>:9119        Hermes dashboard
├── macOS        → ssh agents@orb               OrbStack built-in SSH
└── VM → LAN     → http://llm.internal:8000/v1  oMLX (Mac Studio M3 Ultra), Home Assistant
```

## Decisions

| Topic | Decision | Reason |
|---|---|---|
| Hypervisor | OrbStack Linux machine, installed by Ansible (`orbstack` cask in `site.yml`) | Lightweight, fast VirtioFS, scriptable `orb` CLI |
| VM count | One machine `agents` | Hermes ↔ OpenCode over localhost; no server password or LAN exposure for OpenCode |
| Isolation | `orb create --isolated --mount ~/agent_workspaces:/workspace` | No `/mnt/mac`, no Mac-host network access, no SSH-agent forwarding |
| Network isolation | Off (no `--isolate-network`) | Hermes must reach Home Assistant and `llm.internal` |
| Resources | `memory_mib=12288`, `cpu=6` | OrbStack limits are global ceilings; memory is released when idle. Leaves ~20 GB / 4 cores for macOS |
| LAN identity | Reached via the Mac's static IP; no own DHCP lease | OrbStack machines are NATed behind the Mac |
| Dashboard | `hermes dashboard --host 0.0.0.0 --port 9119 --no-open`, basic-auth provider (hashed password + signing secret) | Hermes fails closed without auth on non-loopback binds. LAN only; not for internet exposure |
| Remote access | Telegram gateway (`hermes gateway`), `TELEGRAM_ALLOWED_USERS` = owner only | Outbound polling; no inbound ports |
| Hermes → OpenCode | Hermes skill wrapping `opencode run --server http://127.0.0.1:4096 …` | `opencode serve` (v2) is an HTTP API, not MCP; `--workspace` flag doesn't exist — cwd is used |
| Model providers | Anthropic API key + oMLX at `http://llm.internal:8000/v1` (OpenAI-compatible) for both OpenCode (`opencode.json`, `@ai-sdk/openai-compatible`) and Hermes (`config.yaml` custom endpoint) | |
| Gmail + Calendar | `taylorwilsdon/google_workspace_mcp` (`workspace-mcp --read-only --tools gmail calendar`), registered under `mcp_servers` in Hermes | Read-only enforced by OAuth scopes; multi-account per session. Hermes' bundled skill stores one token per profile and grants modify scopes |
| Google Cloud | One project + one Desktop OAuth client (owned by any account), user type External, published to Production unverified | Covers all inboxes; avoids 7-day refresh-token expiry of Testing mode |
| Approvals | Hermes approval mode stays on (smart/manual) | Inbox content is untrusted (prompt injection) |
| Matt Pocock skills | Installed in the VM for OpenCode via a shared `matt_skills` role (refactored out of `site.yml`) | One implementation for Mac and VM |
| GitHub access | Fine-grained PAT (`flungster/mac-setup`, `flungster/health-tracker`; Contents/Issues/PRs RW), `gh auth setup-git`, `url."https://github.com/".insteadOf "git@github.com:"` | PATs are HTTPS-only; insteadOf keeps SSH-style URLs working. Covers git and `gh`-based skills |
| Git identity | `Felix Lung <felix.lung@gmail.com>` | Agent commits distinguished by the `Generated with opencode — model(s): …` trailer (AGENTS.md) |
| Hermes on macOS | Removed from the Mac setup (bootstrap prompt, `install_hermes_agent`, tasks, tests, README). Not installed on this Mac; nothing to uninstall | Hermes lives in the VM. Playbook does not uninstall (ADR-0001) |
| Code location | This repo; opt-in `playbooks/agents-vm.yml` | Same bootstrap; doesn't run unless requested |

## Gmail accounts

| Account | Type | Notes |
|---|---|---|
| `felix.lung@gmail.com` | Personal Gmail | Most sensitive inbox. Read-only scopes; consider excluding from scheduled/automated summaries initially |
| `flungster@gmail.com` | Personal Gmail | High promo/order volume — good first account to validate setup and prompt-injection handling |
| `fl10@cornell.edu` | **Google Workspace for Education (Cornell-managed)** | Not a personal account: Cornell IT controls third-party app access. Admin policy may block an unverified OAuth app or restricted Gmail scopes (`gmail.readonly`). Check Cornell's acceptable-use / data policy before sending university mail to Anthropic. Treat as best-effort; plan works without it |

Rollout order: `flungster` → `felix.lung` → `fl10@cornell.edu`.

## Repo changes

### Mac (`playbooks/site.yml`, `bootstrap.sh`)
- Add `orbstack` cask (presence-gated per ADR-0001).
- Remove Hermes Agent: bootstrap prompt, `INSTALL_HERMES_AGENT` / `install_hermes_agent`, tasks, tests, README section; drop **Optional app** from `CONTEXT.md` if unused.
- Extract Matt skills tasks into `playbooks/roles/matt_skills` (params: home, agent targets, marker paths, lock path); Mac keeps `codex` + `claude-code`.

### New `playbooks/agents-vm.yml` + roles
- `orbstack_vm` (runs on Mac): assert `orb`; `orb config set memory_mib/cpu`; create `~/agent_workspaces`; create machine only if absent; reconcile `machine.agents.mounts`; add inventory host via OrbStack SSH (`agents@orb`).
- `agents_base` (VM): apt packages (`git curl unzip build-essential python3 python3-venv jq`), Node.js LTS, `uv`, unprivileged service user, linger for user services if needed.
- `github_access` (VM): install `gh`; `gh auth login --with-token`; `gh auth setup-git`; insteadOf rewrite; git identity; clone `agent_repos` into `/workspace` if missing.
- `opencode_server` (VM): official installer; `opencode.json` (Anthropic + oMLX provider); `/etc/opencode/env` (0600); `opencode-server.service` (`--hostname 127.0.0.1 --port 4096`, `WorkingDirectory=/workspace`, `Restart=on-failure`, enabled).
- `matt_skills` (VM, as service user): shared role, no extra agent targets (OpenCode reads `~/.agents/skills`).
- `hermes_agent` (VM): official installer (non-interactive); `~/.hermes/.env` (0600: `ANTHROPIC_API_KEY`, dashboard basic-auth vars, Telegram vars); `config.yaml` (models, approvals, `mcp_servers`); OpenCode bridge skill; `hermes-dashboard.service`, `hermes-gateway.service`.
- `google_workspace_mcp` (VM): install via `uv tool`; OAuth client from Vault; systemd service bound to loopback, `--read-only --tools gmail calendar`; register in Hermes `mcp_servers`.

### Vars and secrets
- `group_vars` / play vars: `agents_vm_name: agents`, `agents_vm_memory_mib: 12288`, `agents_vm_cpu: 6`, `agents_vm_workspace_host_path: "{{ ansible_env.HOME }}/agent_workspaces"`, `opencode_port: 4096`, `hermes_dashboard_port: 9119`, `local_llm_base_url: http://llm.internal:8000/v1`, `local_llm_models: [...]`, `git_user_name`, `git_user_email`, `agent_repos`, `gmail_accounts`.
- Vault file (+ committed `.example`): `anthropic_api_key`, `hermes_dashboard_username`, `hermes_dashboard_password_hash`, `hermes_dashboard_secret`, `telegram_bot_token`, `telegram_allowed_users`, `google_oauth_client_id`, `google_oauth_client_secret`, `github_token`; later `home_assistant_token`.

### Docs and tests
- `CONTEXT.md`: terms **Agents VM**, **Workspace**.
- ADR: run agents in an isolated OrbStack machine (alternatives: two VMs, Lima/UTM bridged, macOS-native).
- README: human-only steps (below), how to run `agents-vm.yml`, how to rotate secrets.
- Offline stub tests in the `make test` style; `make verify` gains agents-VM checks.

## Human-only steps

1. Telegram: create bot with @BotFather; get numeric user ID from @userinfobot.
2. Google Cloud: one project; enable Gmail + Calendar APIs; consent screen **External**; publish to **Production**; create **Desktop app** OAuth client.
3. GitHub: fine-grained PAT — owner `flungster`, repos `mac-setup` + `health-tracker`; Contents, Issues, Pull requests = Read and write; choose expiry (~1 year).
4. Fill the Vault file; choose the Vault password.
5. After provisioning: authorize each Gmail account once (browser link; SSH tunnel to the VM's callback port if needed). Click through "unverified app" warning.
6. Optional: confirm OrbStack settings in the app on first launch.

## Verification

- `ssh agents@orb` works; `orb list` shows `agents` as isolated.
- From another LAN device, `http://<mac-ip>:9119` prompts for login; `/api/status` reports `auth_required: true`, provider `basic`. If unreachable, check `machines.expose_ports_to_lan` for isolated machines.
- Telegram: owner gets replies; other users are ignored.
- Hermes → OpenCode task edits a file in `/workspace/<repo>`, visible in `~/agent_workspaces/<repo>` on the Mac.
- Both providers answer; `curl http://llm.internal:8000/v1/models` succeeds inside the VM.
- Each Gmail account: list unread + upcoming events; a send attempt is refused (read-only).
- VM reaches Home Assistant and `llm.internal`; cannot read Mac paths outside `/workspace`; cannot reach the Mac host.
- `gh auth status` OK; `git ls-remote` works for both repos (push test opt-in, not in default `make verify`).
- Matt skills present in VM; OpenCode lists them.
- Re-running `agents-vm.yml` reports no changes.

## Work order (tracer bullets)

1. Mac: remove Hermes; add OrbStack cask.
2. Extract shared `matt_skills` role (Mac behaviour unchanged, tests green).
3. OrbStack + VM: limits, isolated machine, workspace mount, SSH inventory. *(needs 1)*
4. VM base + GitHub access + repo clones. *(needs 3)*
5. OpenCode server with Anthropic + oMLX; Matt skills in VM. *(needs 2, 4)*
6. Hermes + dashboard (auth) + providers. *(needs 3)*
7. Hermes → OpenCode bridge skill. *(needs 5, 6)*
8. Telegram gateway. *(needs 6)*
9. Google Workspace MCP, read-only, three accounts. *(needs 6)*
10. Docs/ADR/CONTEXT/verify — alongside each step.

## Deferred

- Home Assistant MCP integration.
- Gmail send (drop `--read-only`, re-consent).
- UniFi DNS name for the Mac IP; remote dashboard via Tailscale or UniFi VPN.

## Open items

- oMLX model IDs to expose (from `curl http://llm.internal:8000/v1/models`) and which is the default for Hermes vs OpenCode.
- Default Anthropic model for each agent.
- Whether Cornell permits third-party OAuth access to `fl10@cornell.edu`.
- Whether the dashboard should start on boot or only on demand.

## Changes since implementation (docs/plans/orbstack-opt-in.md)

- **OrbStack is not in the Mac baseline any more.** The `orbstack` cask was removed from `playbooks/site.yml`; the agents-VM playbook installs or updates OrbStack itself, only when you opt in (ADR 0001's rules still apply: manual installs are left alone).
- **Opt-in is a bootstrap question** — "Install/update OrbStack and the agents VM (Hermes Agent + OpenCode)? [y/N]" — asked on every run, default No, and a no-terminal bootstrap answers No without hanging. `PROVISION_AGENTS_VM` still pre-answers it for automation; on "yes", the vault password is read from `AGENTS_VAULT_PASSWORD_FILE` or asked interactively (`--ask-vault-pass`).
- **Answering "yes" without a secrets file stops the bootstrap before anything is installed**, pointing at `playbooks/secrets/agents-vm-secrets.example.yml`.
