# mac-setup
Setup and maintain apps that I typically install on a fresh new Mac install

## Built 100% by AI agents

This repo is written entirely by AI coding agents: every line of shell, Ansible, tests and docs was produced in [opencode](https://opencode.ai) sessions — the human directs, reviews and pushes. That attribution lives in git history: each commit message ends with a trailer naming the harness and model(s) used (see `AGENTS.md` → commit messages). Different opencode stages run different models — Claude Opus plans, Qwen 3.8 (a `brain` in a trailer) builds — and the trailer lists every model that contributed to the change.

## Before you start

Install your password manager (e.g. 1Password) manually **before** cloning — you need it to authenticate git. Provisioning never touches apps that are already present on the machine, brew-managed or manual (see `docs/adr/0001-skip-install-if-app-already-present.md`).

## How to run

On the Mac you want provisioned (fresh or existing):

```sh
git clone git@github.com:flungster/mac-setup.git
cd mac-setup
./bootstrap.sh        # or: make setup
```

That's it. `bootstrap.sh` ensures, in order: Command Line Tools (a system dialog appears on a fresh Mac; bootstrap waits until the install actually finishes), the Xcode license when full Xcode is active (`sudo xcodebuild -license accept` — may prompt for your password; updates reset acceptance), Homebrew, and Ansible. It also adds `eval "$(brew shellenv)"` to your `~/.zprofile`, so new terminals find brew. Then it runs the provision playbook.

**Re-running is the update path.** Run `./bootstrap.sh` again to keep brew-managed apps in the inventory current and install anything missing. Apps that are present but not brew-managed (e.g. a manually installed 1Password) are never touched, by install or upgrade.

The managed inventory — what actually gets installed/upgraded — lives in `playbooks/site.yml` (currently: 1Password, iTerm2, Visual Studio Code, Claude Code and Codex as casks; opencode, emacs, gh, uv, node and shellcheck as formulas; plus Oh My Zsh).

**OrbStack and the agents VM are opt-in, behind one question.** On every run bootstrap asks: *Install/update OrbStack and the agents VM (Hermes Agent + OpenCode)? [y/N]* — default No. A "yes" installs or updates OrbStack (it is **not** in the baseline above) and provisions its isolated virtual machine via `playbooks/agents-vm.yml`; a "no" leaves both exactly as they are. See [Agents VM](#agents-vm-hermes-agent--opencode-in-a-linux-virtual-machine).

Matt Pocock's agent skills are installed globally with the open `skills` CLI (always at its latest release). One shared set lives in `~/.agents/skills` for OpenCode and Codex; Claude Code receives symlinks in `~/.claude/skills`. Re-running bootstrap updates them only when the upstream lock actually changes. After a fresh run, sign in with `claude` and `codex login`, then run `/setup-matt-pocock-skills` once in each repo.

Oh My Zsh isn't in Homebrew, so it's installed with its official script, only when `~/.oh-my-zsh` (or `$ZSH`) doesn't exist yet. The script runs unattended and never replaces an existing `~/.zshrc`. On a fresh Mac, with no `~/.zshrc`, you get the Oh My Zsh template. On a Mac that already has one, add the Oh My Zsh lines to it yourself (see `~/.oh-my-zsh/templates/minimal.zshrc`). Oh My Zsh updates itself, so re-running bootstrap doesn't upgrade it.

On an already-bootstrapped machine you can also run just the playbook:

```sh
eval "$(/opt/homebrew/bin/brew shellenv)"   # /usr/local on Intel Macs
ansible-playbook -i playbooks/hosts -e 'homebrew_path=""' playbooks/site.yml
```

The agents VM (and with it OrbStack) is skipped unless you answer yes to the question above: `PROVISION_AGENTS_VM=1 ./bootstrap.sh` pre-answers it for automation (plus `AGENTS_VAULT_PASSWORD_FILE`, see below), or run the playbook directly:

```sh
ansible-playbook -i playbooks/hosts --vault-password-file <file> playbooks/agents-vm.yml
```

## Agents VM (Hermes Agent + OpenCode in a Linux virtual machine)

One isolated OrbStack machine named `agents` (Ubuntu 24.04, ARM64) runs **Hermes Agent** — the agent you talk to from any LAN device via its web dashboard, or through Telegram when away — and **OpenCode**, the coding agent it hands work to. The design is documented in [`docs/plans/agents-vm.md`](docs/plans/agents-vm.md) and decided in [`docs/adr/0002-agents-via-orbstack-machine.md`](docs/adr/0002-agents-via-orbstack-machine.md).

What the playbook does (re-running is the update path): sets OrbStack's memory/CPU ceilings, creates `~/agent_workspaces` and the isolated machine (shared only as `/workspace`, with clones of your personal repos), then inside the VM installs and configures OpenCode (Anthropic + your local oMLX server), Hermes Agent (dashboard with username/password login, Telegram gateway, the OpenCode bridge skill) and read-only Gmail/Calendar access through `workspace-mcp`. Claude Code and Codex are installed there too, for you to use over SSH (`orb -m agents`) — the playbook can't sign them in, so each run reminds you until you have run `claude` (then `/login`) and `codex login --device-auth` once in the VM. Both share the Mac's Matt Pocock skills set.

**Opt-in.** It never runs by default. On every interactive run bootstrap asks:

```text
Install/update OrbStack and the agents VM (Hermes Agent + OpenCode)? [y/N]
```

Default No — and it is asked even when a VM already exists, because "yes" on an existing machine is the update path (OrbStack updated if brew-managed and outdated; machine reconciled, never recreated). A bootstrap with no terminal attached answers No without hanging. Automation pre-answers:

```sh
PROVISION_AGENTS_VM=1 AGENTS_VAULT_PASSWORD_FILE=~/.config/mac-setup/agents-vm-vault-pass ./bootstrap.sh
```

**First OrbStack start shows its own window.** On a Mac where OrbStack was just installed, the playbook's `orb start` launches the app for the first time. OrbStack then shows its welcome screen ("Docker / Linux / Kubernetes") and may ask for your password to install its helper. Do **not** pick Linux there: that creates a separate default machine (`ubuntu`) that this setup doesn't use, since the playbook creates `agents` itself. Close the welcome screen instead. If you already picked Linux, delete the extra machine (`orb delete ubuntu`, or in the OrbStack window). Later runs don't show the welcome screen again.

Answering "yes" without the secrets file stops bootstrap before anything is installed, pointing at the template below. The vault password comes from `AGENTS_VAULT_PASSWORD_FILE` when set; otherwise Ansible asks for it interactively (`--ask-vault-pass`).

**Secrets, with ansible-vault (step by step).** The keys live in `playbooks/secrets/agents-vm-secrets.yml`, encrypted with Ansible Vault; only the keys you fill in are real, and both this file's name (in `.gitignore`) and its password stay out of git. Only `anthropic_api_key` and `hermes_dashboard_password` are required; the rest (Telegram, Google OAuth client, GitHub PAT, oMLX key) enable their features when present.

1. **Get Ansible first (fresh Mac only).** `ansible-vault` ships with the Ansible formula that bootstrap installs — so on a fresh Mac run `./bootstrap.sh` once and answer **n** to the agents-VM question (everything else installs; OrbStack is left alone), then come back here.
2. **Create a vault password file** — one line holding only the vault password, outside the repo:
   ```sh
   mkdir -p ~/.config/mac-setup
   echo 'your-strong-password-here' > ~/.config/mac-setup/agents-vm-vault-pass
   chmod 600 ~/.config/mac-setup/agents-vm-vault-pass
   ```
3. **Copy the template, fill it in, then encrypt.** First attempt only — once a file is encrypted you use `edit` (step 6):
   ```sh
   cp playbooks/secrets/agents-vm-secrets.example.yml \
      playbooks/secrets/agents-vm-secrets.yml
   $EDITOR playbooks/secrets/agents-vm-secrets.yml     # fill it in, plain text
   ansible-vault encrypt --vault-password-file ~/.config/mac-setup/agents-vm-vault-pass \
      playbooks/secrets/agents-vm-secrets.yml
   ```
   Fill `anthropic_api_key` and `hermes_dashboard_password`, plus any optional keys you already have (the template's comments explain each). Note: `ansible-vault edit` on a still-plaintext file would just save it as plaintext — that is why the first pass uses `encrypt`.
4. **Check it is really encrypted:** `cat playbooks/secrets/agents-vm-secrets.yml` must start with `$ANSIBLE_VAULT;1.1;AES256`. To read it again: `ansible-vault view --vault-password-file ~/.config/mac-setup/agents-vm-vault-pass playbooks/secrets/agents-vm-secrets.yml`.
5. **Run with it.** Hand bootstrap the password file and answer y: `AGENTS_VAULT_PASSWORD_FILE=~/.config/mac-setup/agents-vm-vault-pass ./bootstrap.sh` — or run the playbook directly: `ansible-playbook -i playbooks/hosts --vault-password-file ~/.config/mac-setup/agents-vm-vault-pass playbooks/agents-vm.yml`. Omit the password file and Ansible asks for it interactively instead of failing.
6. **When a key changes later:** the file is already encrypted, so it's `edit`, not step 3's `encrypt`:
   ```sh
   ansible-vault edit --vault-password-file ~/.config/mac-setup/agents-vm-vault-pass \
      playbooks/secrets/agents-vm-secrets.yml
   ```
   Then re-run with "yes" (see Rotating secrets below).

**Rotating secrets.** Edit the vault file (`ansible-vault edit playbooks/secrets/agents-vm-secrets.yml`) and re-run with "yes" (or the playbook directly). What each rotation needs:
- **GitHub PAT:** delete `~/.config/gh` inside the VM first — otherwise the cached login is still "valid" and the new token is never applied.
- **Dashboard signing secret:** remove the `HERMES_DASHBOARD_BASIC_AUTH_SECRET=` line from `~/.hermes/.env` inside the VM; it is generated once and kept stable, so deleting rotates it (existing dashboard sessions die).
- **Everything else** (dashboard password, Telegram token, Google OAuth client, oMLX key): re-applied on the next run — Hermes' `.env` is managed per key, and config files are rewritten wholesale.

**Steps only you can do:** create the Telegram bot with @BotFather and get your user ID from @userinfobot; set up a Google Cloud project (Gmail + Calendar APIs, External consent screen published to Production without review, one Desktop-app OAuth client); create a fine-grained GitHub PAT for `flungster/mac-setup` and `flungster/health-tracker`. Full walkthrough: see the plan's "Human-only steps" section. After provisioning, sign in once per Gmail account through a browser link (an SSH tunnel to the VM if your browser can't reach it) — in rollout order, `flungster@gmail.com` (noisy inbox: good first validation), then `felix.lung@gmail.com`, and `fl10@cornell.edu` best-effort (Cornell admin may block it). The playbook ends a run with the Google client configured by reminding you of this list (`gmail_accounts` in `playbooks/vars_agents_vm.yml`).

**Reaching the agents:** `orb -m agents` from macOS (a shell in the VM; `ssh agents@orb` also works once OrbStack has added its SSH config to `~/.ssh/config`); dashboard at `http://<mac-ip>:9119` (username/password) from any LAN device; Telegram anywhere. The VM is NATed behind the Mac, so it has no IP of its own on your network.

## Development

- `make check` — bash syntax + shellcheck over all scripts and test stubs. shellcheck is a hard requirement (bootstrap installs it); `SKIP_SHELLCHECK=1` runs bash syntax only
- `make test`  — offline, stub-based tests; nothing real is installed (provisions `.test-venv` as needed)
- `make verify` — real-machine smoke checks after bootstrap (Claude Code, Codex, Node.js and the Matt Pocock skills); never installs

