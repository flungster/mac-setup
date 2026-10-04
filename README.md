# mac-setup
Setup and maintain apps that I typically install on a fresh new Mac install

## Built 100% by AI agents

This repo is written entirely by AI coding agents: every line of shell, Ansible, tests and docs was produced in [opencode](https://opencode.ai) sessions — the human directs, reviews and pushes. That attribution lives in git history: each commit message ends with a trailer naming the harness and model(s) used (see `AGENTS.md` → commit messages).

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

**OrbStack is in the inventory so this Mac can host the agents VM.** The virtual machine itself (Hermes Agent + OpenCode, provisioned by `playbooks/agents-vm.yml`) is opt-in and not run by default — see [Agents VM](#agents-vm-hermes-agent--opencode-in-a-linux-virtual-machine).

Matt Pocock's agent skills are installed globally with the open `skills` CLI (always at its latest release). One shared set lives in `~/.agents/skills` for OpenCode and Codex; Claude Code receives symlinks in `~/.claude/skills`. Re-running bootstrap updates them only when the upstream lock actually changes. After a fresh run, sign in with `claude` and `codex login`, then run `/setup-matt-pocock-skills` once in each repo.

Oh My Zsh isn't in Homebrew, so it's installed with its official script, only when `~/.oh-my-zsh` (or `$ZSH`) doesn't exist yet. The script runs unattended and never replaces an existing `~/.zshrc`. On a fresh Mac, with no `~/.zshrc`, you get the Oh My Zsh template. On a Mac that already has one, add the Oh My Zsh lines to it yourself (see `~/.oh-my-zsh/templates/minimal.zshrc`). Oh My Zsh updates itself, so re-running bootstrap doesn't upgrade it.

On an already-bootstrapped machine you can also run just the playbook:

```sh
eval "$(/opt/homebrew/bin/brew shellenv)"   # /usr/local on Intel Macs
ansible-playbook -i playbooks/hosts -e 'homebrew_path=""' playbooks/site.yml
```

The agents VM is skipped unless you opt in: `PROVISION_AGENTS_VM=1 ./bootstrap.sh` (plus `AGENTS_VAULT_PASSWORD_FILE`, see below), or run the playbook directly:

```sh
ansible-playbook -i playbooks/hosts --vault-password-file <file> playbooks/agents-vm.yml
```

## Agents VM (Hermes Agent + OpenCode in a Linux virtual machine)

One isolated OrbStack machine named `agents` (Ubuntu 24.04, ARM64) runs **Hermes Agent** — the agent you talk to from any LAN device via its web dashboard, or through Telegram when away — and **OpenCode**, the coding agent it hands work to. The design is documented in [`docs/plans/agents-vm.md`](docs/plans/agents-vm.md) and decided in [`docs/adr/0002-agents-via-orbstack-machine.md`](docs/adr/0002-agents-via-orbstack-machine.md).

What the playbook does (re-running is the update path): sets OrbStack's memory/CPU ceilings, creates `~/agent_workspaces` and the isolated machine (shared only as `/workspace`, with clones of your personal repos), then inside the VM installs and configures OpenCode (Anthropic + your local oMLX server), Hermes Agent (dashboard with username/password login, Telegram gateway, the OpenCode bridge skill) and read-only Gmail/Calendar access through `workspace-mcp`.

**Opt-in.** It never runs by default. On this Mac:

```sh
PROVISION_AGENTS_VM=1 AGENTS_VAULT_PASSWORD_FILE=~/.config/mac-setup/agents-vm-vault-pass ./bootstrap.sh
```

**Secrets.** `playbooks/secrets/agents-vm-secrets.yml` holds the API keys and tokens. Copy `playbooks/secrets/agents-vm-secrets.example.yml`, fill it in, encrypt it (`ansible-vault encrypt --vault-password-file <file> playbooks/secrets/agents-vm-secrets.yml`), and keep both the file and its password out of git. Only `anthropic_api_key` and `hermes_dashboard_password` are required; the rest (Telegram, Google OAuth client, GitHub PAT, oMLX key) enable their features when present.

**Steps only you can do:** create the Telegram bot with @BotFather and get your user ID from @userinfobot; set up a Google Cloud project (Gmail + Calendar APIs, External consent screen published to Production without review, one Desktop-app OAuth client); create a fine-grained GitHub PAT for `flungster/mac-setup` and `flungster/health-tracker`. Full walkthrough: see the plan's "Human-only steps" section. After provisioning, sign in once per Gmail account through a browser link (an SSH tunnel to the VM if your browser can't reach it).

**Reaching the agents:** `ssh agents@orb` from macOS; dashboard at `http://<mac-ip>:9119` (username/password) from any LAN device; Telegram anywhere. The VM is NATed behind the Mac, so it has no IP of its own on your network.

## Development

- `make check` — bash syntax + shellcheck over all scripts and test stubs. shellcheck is a hard requirement (bootstrap installs it); `SKIP_SHELLCHECK=1` runs bash syntax only
- `make test`  — offline, stub-based tests; nothing real is installed (provisions `.test-venv` as needed)
- `make verify` — real-machine smoke checks after bootstrap (Claude Code, Codex, Node.js and the Matt Pocock skills); never installs

