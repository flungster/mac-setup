# Plan: agents VM (Hermes Agent + OpenCode) on the Mac Studio

Status: implemented — every tracer bullet below has landed (see git history). Changes made after implementation are recorded at the end of this file and in `docs/plans/orbstack-opt-in.md`.

## Goal

One isolated Linux VM on the Mac Studio (M1 Max, 32 GB, static LAN IP) runs **Hermes Agent** (orchestrator) and **OpenCode** (coding agent), provisioned by Ansible from this repo and reachable over SSH from macOS. Hermes is used:

- from any LAN device via its web dashboard, and
- from anywhere via Telegram,

and can reach the LAN (Home Assistant, the oMLX server), draft and manage three Gmail inboxes with full Calendar access (no sending — the levels are `google_workspace_permissions`), and drive OpenCode against personal GitHub repos.

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
│       └── google-workspace-mcp.service 127.0.0.1        (--permissions levels, gmail+calendar)
│
├── LAN devices  → http://<mac-ip>:9119        Hermes dashboard
├── macOS        → ssh <macOS user>@agents (127.0.0.1:32222)  OrbStack's SSH server
└── VM → LAN     → http://llm.internal:8000/v1  oMLX (Mac Studio M3 Ultra), Home Assistant
```

## Decisions

| Topic | Decision | Reason |
|---|---|---|
| Hypervisor | OrbStack Linux machine; installed/updated by the agents-VM playbook itself only when opted in — not part of the Mac baseline (see "Changes since implementation") | Lightweight, fast VirtioFS, scriptable `orb` CLI |
| VM count | One machine `agents` | Hermes ↔ OpenCode over localhost; no server password or LAN exposure for OpenCode |
| Isolation | `orb create --isolated --mount ~/agent_workspaces:/workspace` | No `/mnt/mac`, no Mac-host network access, no SSH-agent forwarding |
| Network isolation | Off (no `--isolate-network`) | Hermes must reach Home Assistant and `llm.internal` |
| Resources | `memory_mib=12288`, `cpu=6` | OrbStack limits are global ceilings; memory is released when idle. Leaves ~20 GB / 4 cores for macOS |
| LAN identity | Reached via the Mac's static IP; no own DHCP lease | OrbStack machines are NATed behind the Mac |
| Dashboard | `hermes dashboard --host 0.0.0.0 --port 9119 --no-open`, basic-auth provider (hashed password + signing secret) | Hermes fails closed without auth on non-loopback binds. LAN only; not for internet exposure |
| Remote access | Telegram gateway (`hermes gateway`), `TELEGRAM_ALLOWED_USERS` = owner only | Outbound polling; no inbound ports |
| Hermes → OpenCode | Hermes skill wrapping `opencode run --server http://127.0.0.1:4096 …` | `opencode serve` (v2) is an HTTP API, not MCP; `--workspace` flag doesn't exist — cwd is used |
| Model providers | Anthropic API key + oMLX at `http://llm.internal:8000/v1` (OpenAI-compatible) for both OpenCode (`opencode.json`, `@ai-sdk/openai-compatible`) and Hermes (`config.yaml` custom endpoint) | |
| Gmail + Calendar | `taylorwilsdon/google_workspace_mcp` as its own LAN service (OAuth 2.1 multi-user, port `workspace_mcp_port`); one OAuth-protected `mcp_servers` entry per account in Hermes | Per-service levels from `google_workspace_permissions`, rendered as one `--permissions <service>:<level>` list (gmail=drafts = draft box + labels/archive but no send; calendar=full); one browser consent per account (dashboard's MCP page) — raising a level needs each stored token re-consented, but restarts never do |
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
| `felix.lung@gmail.com` | Personal Gmail | Most sensitive inbox. Draft-level access (no send); consider excluding from scheduled/automated summaries initially |
| `flungster@gmail.com` | Personal Gmail | High promo/order volume — good first account to validate setup and prompt-injection handling |
| `fl10@cornell.edu` | **Google Workspace for Education (Cornell-managed)** | Not a personal account: Cornell IT controls third-party app access. Admin policy may block an unverified OAuth app or restricted Gmail scopes (`gmail.readonly`). Check Cornell's acceptable-use / data policy before sending university mail to Anthropic. Treat as best-effort; plan works without it |

Rollout order: `flungster` → `felix.lung` → `fl10@cornell.edu`.

## Repo changes

### Mac (`playbooks/site.yml`, `bootstrap.sh`)
- Add `orbstack` cask (presence-gated per ADR-0001).
- Remove Hermes Agent: bootstrap prompt, `INSTALL_HERMES_AGENT` / `install_hermes_agent`, tasks, tests, README section; drop **Optional app** from `CONTEXT.md` if unused.
- Extract Matt skills tasks into `playbooks/roles/matt_skills` (params: home, agent targets, marker paths, lock path); Mac keeps `codex` + `claude-code`.

### New `playbooks/agents-vm.yml` + roles
- `orbstack_vm` (runs on Mac): assert `orb`; `orb config set memory_mib/cpu`; create `~/agent_workspaces`; create machine only if absent; reconcile `machine.agents.mounts`; add inventory host via OrbStack's SSH server (`<macOS user>@agents` on 127.0.0.1:32222 — not the `orb` alias, which needs OrbStack's Include in `~/.ssh/config`).
- `agents_base` (VM): apt packages (`git curl unzip build-essential python3 python3-venv jq`), Node.js LTS, `uv`, unprivileged service user, linger for user services if needed.
- `github_access` (VM): install `gh`; `gh auth login --with-token`; `gh auth setup-git`; insteadOf rewrite; git identity; clone `agent_repos` into `/workspace` if missing.
- `opencode_server` (VM): official installer; `opencode.json` (Anthropic + oMLX provider); `/etc/opencode/env` (0600); `opencode-server.service` (`--hostname 127.0.0.1 --port 4096`, `WorkingDirectory=/workspace`, `Restart=on-failure`, enabled).
- `matt_skills` (VM, as service user): shared role, no extra agent targets (OpenCode reads `~/.agents/skills`).
- `hermes_agent` (VM): official installer (non-interactive); `~/.hermes/.env` (0600: `ANTHROPIC_API_KEY`, dashboard basic-auth vars, Telegram vars); `config.yaml` (models, approvals, `mcp_servers`); OpenCode bridge skill; `hermes-dashboard.service`, `hermes-gateway.service`.
- `google_workspace_mcp` (VM): install via `uv tool`; OAuth client keys per-key in a 0600 env file (from Vault); `workspace-mcp.service` on port `workspace_mcp_port`, OAuth 2.1 multi-user, LAN-reachable (`--permissions` levels from `google_workspace_permissions`: gmail=drafts, calendar=full); `hermes_agent` writes one OAuth-protected `mcp_servers` entry per account.

### Vars and secrets
- `group_vars` / play vars: `agents_vm_name: agents`, `agents_vm_memory_mib: 12288`, `agents_vm_cpu: 6`, `agents_vm_workspace_host_path: "{{ ansible_env.HOME }}/agent_workspaces"`, `opencode_port: 4096`, `hermes_dashboard_port: 9119`, `local_llm_base_url: http://llm.internal:8000/v1`, `local_llm_models: [...]`, `git_user_name`, `git_user_email`, `agent_repos`, `google_workspace_accounts` (name + email per account), `google_workspace_permissions`, `workspace_mcp_port`.
- Vault file (+ committed `.example`): `anthropic_api_key`, `hermes_dashboard_username`, `hermes_dashboard_password_hash`, `hermes_dashboard_secret`, `telegram_bot_token`, `telegram_allowed_users`, `google_oauth_client_id`, `google_oauth_client_secret`, `github_token`; later `home_assistant_token`.

### Docs and tests
- `CONTEXT.md`: terms **Agents VM**, **Workspace**.
- ADR: run agents in an isolated OrbStack machine (alternatives: two VMs, Lima/UTM bridged, macOS-native).
- README: human-only steps (below), how to run `agents-vm.yml`, how to rotate secrets.
- Offline stub tests in the `make test` style; `make verify` gains agents-VM checks.

## Human-only steps

1. Telegram: create bot with @BotFather; get numeric user ID from @userinfobot.
2. Google Cloud: one project; enable Gmail + Calendar APIs; consent screen **External**; publish to **Production**; create a **Desktop app** OAuth client and add its redirect URI `http://localhost:9120/oauth2callback` (the workspace-mcp port, `workspace_mcp_port`).
3. GitHub: fine-grained PAT — owner `flungster`, repos `mac-setup` + `health-tracker`; Contents, Issues, Pull requests = Read and write; choose expiry (~1 year).
4. Fill the Vault file; choose the Vault password.
5. After provisioning: open the Hermes dashboard (MCP page) and authenticate each `google_workspace_*` entry once, picking that Google account in the browser — do this from a browser ON THIS MAC: the consent URL is `http://127.0.0.1:<workspace_mcp_port>/authorize`, which OrbStack forwards to the VM (no SSH tunnel; from other LAN devices that URL would point at their own loopback). Click through "unverified app" warning; authenticated accounts keep their credentials across reboots and service restarts.
6. After provisioning, in the VM (`orb -m agents`): sign Claude Code and Codex in once — run `claude`, then `/login`; `codex login --device-auth`. The playbook can't sign them in; it reminds you on every run until both are done.
7. Optional: confirm OrbStack settings in the app on first launch.

## Verification

- From the Mac, `orb -m agents` opens a shell in the VM (ssh to 127.0.0.1:32222 as your Mac user — the `<macOS user>@agents` login the playbook uses — works too); `orb list` shows `agents` as isolated.
- From another LAN device, `http://<mac-ip>:9119` prompts for login; `/api/status` reports `auth_required: true`, provider `basic`. If unreachable, check `machines.expose_ports_to_lan` for isolated machines.
- Telegram: owner gets replies; other users are ignored.
- Hermes → OpenCode task edits a file in `/workspace/<repo>`, visible in `~/agent_workspaces/<repo>` on the Mac.
- Both providers answer; `curl http://llm.internal:8000/v1/models` succeeds inside the VM.
- Each Gmail account: list unread + upcoming events; drafting and label/archive operations work, but sending is refused (the gmail level stops at drafts).
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
9. Google Workspace MCP (per-service permission levels), three accounts. *(needs 6)*
10. Docs/ADR/CONTEXT/verify — alongside each step.

## Deferred

- Home Assistant MCP integration.
- Gmail send (raise the gmail level in `google_workspace_permissions`; each account re-consents).
- UniFi DNS name for the Mac IP; remote dashboard via Tailscale or UniFi VPN.

## Open items

- Whether Cornell permits third-party OAuth access to `fl10@cornell.edu`.

Resolved open items:
- **Default model for each agent** — both default to a local oMLX model now (the spec assumed Anthropic): Hermes via `hermes_default_provider: custom:omlx` / `hermes_default_model: brain`, OpenCode via `opencode_default_model`. See the "local default model" deviation below.
- **oMLX model IDs** — `local_llm_models` lists `brain`, `more-brain`, `local-flash`, `nemo-fast`; Hermes defaults to `brain`, OpenCode to `more-brain`.
- **Dashboard on boot or on demand** — it is a systemd unit, `enable --now` plus `Restart=always`: up at boot and after crashes (see "services restart on config change" below).

## Changes since implementation (docs/plans/orbstack-opt-in.md)

- **OrbStack is not in the Mac baseline any more.** The `orbstack` cask was removed from `playbooks/site.yml`; the agents-VM playbook installs or updates OrbStack itself, only when you opt in (ADR 0001's rules still apply: manual installs are left alone).
- **Opt-in is a bootstrap question** — "Install/update OrbStack and the agents VM (Hermes Agent + OpenCode)? [y/N]" — asked on every run, default No, and a no-terminal bootstrap answers No without hanging. `PROVISION_AGENTS_VM` still pre-answers it for automation; on "yes", the vault password is read from `AGENTS_VAULT_PASSWORD_FILE` or asked interactively (`--ask-vault-pass`).
- **Answering "yes" without a secrets file stops the bootstrap before anything is installed**, pointing at `playbooks/secrets/agents-vm-secrets.example.yml`.
- **`verify.sh` reads its VM knobs** (machine name, dashboard/OpenCode ports) from `playbooks/vars_agents_vm.yml` instead of hard-coding them.
- **Code-review follow-ups:** `gmail_accounts` var (rollout order) with a post-run sign-in reminder when a Google client is configured; `unzip` and `build-essential` restored to the VM base packages; one shared `systemd_unit` role behind all three service units and a looped include for OrbStack's global settings.

- **Claude Code and Codex in the VM** (role `coding_clis`): Claude Code via its native installer (`claude_install_url`), Codex via `npm install -g @openai/codex` with the VM user's npm prefix set to `~/.local` in `~/.npmrc` (no root, and Codex's own update command works). Both presence-gated in `~/.local/bin`; sign-in stays manual with a post-run reminder until `~/.claude/.credentials.json` / `~/.codex/auth.json` exist. The VM's Matt Pocock skills now target `codex` + `claude-code` like the Mac's.

### Accepted deviations (implementation differs from the spec wording above)

- **OpenCode env file** lives at `~/.config/opencode/env` (0600, VM user), not `/etc/opencode/env`.
- **No OpenCode env file any more:** the keys are written into `~/.config/opencode/opencode.json` (0600) instead of `{env:...}` references, because `opencode` run by hand over SSH never loaded the unit's `EnvironmentFile` and called Anthropic without a key.
- **OpenCode server host/port** are set in `opencode.json`'s `server` block, not as unit flags (`--hostname/--port`).
- **Dashboard auth:** the username is a playbook var (`hermes_dashboard_username`, default `admin`); the password goes into the vault in plain (not pre-hashed), and the basic-auth signing secret is generated once by the playbook and kept stable — it does not live in the vault.
- **workspace-mcp runs as its own service in OAuth 2.1 multi-user mode** (superseding the stdio registration): `workspace-mcp.service` (`--transport streamable-http`, port 9120, LAN-reachable — the browser consent and Hermes' dashboard callback both need it), `MCP_ENABLE_OAUTH21=true` with the OAuth client keys in its own 0600 env file, and disk-backed proxy storage so DCR client registrations survive restarts. Hermes' `config.yaml` registers one entry per account (`google_workspace_<name>`: `url` + `auth: oauth`) — each authenticates once on the dashboard's MCP page (picking that Google account; from a browser on this Mac, since the consent URL is `http://127.0.0.1:<port>/authorize` forwarded to the VM by OrbStack), and its tools auto-fill their `user_google_email`, so one entry cannot reach another's inbox. The unit pins `WORKSPACE_MCP_BASE_URI` to that same 127.0.0.1 URL because it must match the `mcp_servers` url Hermes dials exactly — a localhost/127.0.0.1 mismatch aborts the flow with a resource-indicator error — while `GOOGLE_OAUTH_REDIRECT_URI` stays http://localhost because that exact string is what the Google Cloud client registers. The old stdio mode (one session, `user_google_email` passed per call) is gone: OAuth 2.1 mode overrides that parameter from the token identity.
- **VM base packages** final list: `git curl jq ca-certificates python3-venv nodejs unzip build-essential` (`unzip`/`build-essential` restored per the review; `python3` ships with the Ubuntu image). `nodejs` comes from a NodeSource repo pinned to `nodejs_major` (24) — noble ships 18 and the skills CLI needs >= 22.20; NodeSource's nodejs bundles npm/npx, so Ubuntu's `npm` is dropped (it conflicts).
- **The shared unit role's signature:** it takes `unit_name` plus the caller-rendered unit text (`unit_content`, via each role's own template lookup — cross-role `template:` lookups don't resolve against the caller), and a unit's gating (the gateway's token check) is `when:` on the include rather than an `enabled_when` param. Behaviour is byte-identical to the three inlined blocks it replaced.
- **SSH connection reuse off for the VM host:** `ansible_ssh_common_args` carries `-o ControlMaster=no`. Ansible's default multiplexes every task over one SSH connection to OrbStack's proxy, and a stale master there stalled runs mid-task (the next command on the shared connection never executed). No reuse costs one local handshake per task; reliability over speed on a LAN hop.
- **Local default model:** Hermes defaults to oMLX (`hermes_default_provider: custom:omlx`, `hermes_default_model: brain` — both vars in `playbooks/vars_agents_vm.yml`; the spec assumed Anthropic as default). The omlx provider entry lists exactly `local_llm_models` with `discover_models: false`, so the `/model` picker offers only those (the server's full list also includes TTS/STT models). The Linux half fails before touching the VM when an omlx default has no usable model (empty `local_llm_models`, or a default not in the list). OpenCode defaults to local oMLX as well (`opencode_default_model: omlx/more-brain`; its provider lists exactly `local_llm_models`). Per-session switching: `/model custom:omlx:<id>` / `/model anthropic:<id>`.
- **Services restart on config change:** the shared unit role accepts `restart_when_changed` (default false) — hermes-dashboard and hermes-gateway pass it the changed-state of Hermes' `.env` (or `config.yaml`), opencode-server passes its `opencode.json` change, workspace-mcp passes its own OAuth-client env file. A running service only reads those at start, so a rotated key must restart it; an untouched run (or one where only other services' files changed) never kills a service.
- **Dashboard unit parks on exit 78:** `RestartPreventExitStatus=78` — Hermes refuses to start (exit 78) when another dashboard already serves the host; without it, `Restart=always` would loop every 10 s with nothing listening.
