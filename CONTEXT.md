# mac-setup

Provisions a Mac to its desired configuration and keeps it there. Provisioning is idempotent: safe to run on a fresh machine or an existing one, and re-running is the update path.

## Language

**App**:
Software this repo installs and manages on a Mac — GUI apps (casks) as well as CLI tools (formulas), plus the few that Homebrew doesn't carry and that install with their own script (Oh My Zsh).
_Avoid_: package; cask/formula when the whole is meant

**Present**:
An app already installed on the machine, by any means — Homebrew or manually. Provisioning only installs apps that are not present; an app is never treated as absent just because Homebrew does not manage it.
_Avoid_: installed (ambiguous: brew-managed vs on-disk) — say present when the distinction matters

**Optional app**:
An app not every machine wants, installed only when its user opts in (Hermes Agent). Once present it is managed like any other app; declining leaves the machine alone and never asks again.
_Avoid_: feature (sounds like part of this repo's own behaviour); add-on, plugin (sound like parts of some other app)
