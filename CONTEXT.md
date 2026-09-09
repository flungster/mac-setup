# mac-setup

Provisions a Mac to its desired configuration and keeps it there. Provisioning is idempotent: safe to run on a fresh machine or an existing one, and re-running is the update path.

## Language

**App**:
Software this repo installs and manages on a Mac — GUI apps (casks) as well as CLI tools (formulas).
_Avoid_: package; cask/formula when the whole is meant

**Present**:
An app already installed on the machine, by any means — Homebrew or manually. Provisioning only installs apps that are not present; an app is never treated as absent just because Homebrew does not manage it.
_Avoid_: installed (ambiguous: brew-managed vs on-disk) — say present when the distinction matters
