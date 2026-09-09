# Skip install of apps already present on the machine

Provisioning installs an app only if it is not already **present**, and present means installed by any means — Homebrew or manually. A check that only sees what Homebrew manages (`brew list`) is not sufficient: some apps necessarily pre-exist on the machine before this repo's tooling can run. 1Password is the canonical case — it must be installed manually to authenticate with GitHub in order to clone this repo, so every machine provisioning touches already has one. The presence gate is a correctness requirement (leave pre-existing apps alone), not an idempotency optimization.

## Consequences

- A manually pre-existing app is left **entirely** alone: provisioning neither installs nor upgrades it. The scoped `brew upgrade` covers only the brew-managed set (managed casks + formulas minus whatever was already present manually).
- Presence detection therefore needs a second signal beyond `brew list`: casks are checked as `/Applications/<app>.app`, formulas as the binary on `PATH`.
