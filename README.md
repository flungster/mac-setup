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

That's it. `bootstrap.sh` ensures, in order: Command Line Tools (a system dialog appears on a fresh Mac), the Xcode license when full Xcode is active (`sudo xcodebuild -license accept` — may prompt for your password; updates reset acceptance), Homebrew, and Ansible — then runs the provision playbook.

**Re-running is the update path.** Run `./bootstrap.sh` again to keep brew-managed apps in the inventory current and install anything missing. Apps that are present but not brew-managed (e.g. a manually installed 1Password) are never touched, by install or upgrade.

The managed inventory — what actually gets installed/upgraded — lives in `playbooks/site.yml` (currently: 1Password, iTerm2 and Visual Studio Code as casks; opencode, emacs, gh, uv and shellcheck as formulas; plus Oh My Zsh).

Oh My Zsh isn't in Homebrew, so it's installed with its official script, only when `~/.oh-my-zsh` (or `$ZSH`) doesn't exist yet. The script runs unattended and never replaces an existing `~/.zshrc`. On a fresh Mac, with no `~/.zshrc`, you get the Oh My Zsh template. On a Mac that already has one, add the Oh My Zsh lines to it yourself (see `~/.oh-my-zsh/templates/minimal.zshrc`). Oh My Zsh updates itself, so re-running bootstrap doesn't upgrade it.

On an already-bootstrapped machine you can also run just the playbook:

```sh
eval "$(/opt/homebrew/bin/brew shellenv)"   # /usr/local on Intel Macs
ansible-playbook -i playbooks/hosts -e 'homebrew_path=""' playbooks/site.yml
```

## Development

- `make check` — bash syntax + shellcheck over all scripts and test stubs
- `make test`  — offline, stub-based tests; nothing real is installed (provisions `.test-venv` as needed)

