# Skip install of apps already present on the machine

Provisioning installs an app only if it is not already **present**, and present means installed by any means — Homebrew or manually. A check that only sees what Homebrew manages (`brew list`) is not sufficient: some apps necessarily pre-exist on the machine before this repo's tooling can run. 1Password is the canonical case — it must be installed manually to authenticate with GitHub in order to clone this repo, so every machine provisioning touches already has one. The presence gate is a correctness requirement (leave pre-existing apps alone), not an idempotency optimization.

## Consequences

- A manually pre-existing app is left **entirely** alone: provisioning neither installs nor upgrades it. The scoped `brew upgrade` covers only the brew-managed set (managed casks + formulas minus whatever was already present manually).
- Presence detection therefore needs a second signal beyond `brew list`: casks are checked as `/Applications/<app>.app`, formulas as the binary on `PATH`.
- Those signals are deliberately simple, with known edges: a cask installed to `~/Applications` is not seen (only the standard `/Applications`) and gets brew-installed; a formula whose name matches an unrelated system tool on `PATH` (e.g. `/usr/bin/git`) counts as present and is left to the system — point a `bin:` entry at another binary if brew should own it.
