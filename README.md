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

**Hermes Agent is the one optional app.** It's not in that inventory: `bootstrap.sh` asks whether to install it, and a no (or running without a terminal) leaves the machine alone. Answer in advance with `INSTALL_HERMES_AGENT=1` (install) or `0` (skip); a re-run where Hermes is already present keeps it managed without asking again. It installs with its official script (not Homebrew — the formula builds on an unsupported Python), places a source checkout under `~/.hermes` and adds a `hermes` wrapper to your PATH via `~/.local/bin`. Like Oh My Zsh it updates itself, so re-running bootstrap won't upgrade it. After a fresh install, point it at a provider with `hermes model` (or the full wizard: `hermes setup`).

Matt Pocock's agent skills are installed globally with the open `skills` CLI (always at its latest release). One shared set lives in `~/.agents/skills` for OpenCode and Codex; Claude Code receives symlinks in `~/.claude/skills`. Re-running bootstrap updates them only when the upstream lock actually changes. After a fresh run, sign in with `claude` and `codex login`, then run `/setup-matt-pocock-skills` once in each repo.

Oh My Zsh isn't in Homebrew, so it's installed with its official script, only when `~/.oh-my-zsh` (or `$ZSH`) doesn't exist yet. The script runs unattended and never replaces an existing `~/.zshrc`. On a fresh Mac, with no `~/.zshrc`, you get the Oh My Zsh template. On a Mac that already has one, add the Oh My Zsh lines to it yourself (see `~/.oh-my-zsh/templates/minimal.zshrc`). Oh My Zsh updates itself, so re-running bootstrap doesn't upgrade it.

On an already-bootstrapped machine you can also run just the playbook:

```sh
eval "$(/opt/homebrew/bin/brew shellenv)"   # /usr/local on Intel Macs
ansible-playbook -i playbooks/hosts -e 'homebrew_path=""' playbooks/site.yml
```

The optional Hermes Agent is skipped unless you add `-e install_hermes_agent=true` (that's how `bootstrap.sh` forwards your answer to the prompt).

## Development

- `make check` — bash syntax + shellcheck over all scripts and test stubs. shellcheck is a hard requirement (bootstrap installs it); `SKIP_SHELLCHECK=1` runs bash syntax only
- `make test`  — offline, stub-based tests; nothing real is installed (provisions `.test-venv` as needed)
- `make verify` — real-machine smoke checks after bootstrap (Claude Code, Codex, Node.js and the Matt Pocock skills); never installs

