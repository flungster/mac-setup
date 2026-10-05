# mac-setup

Provisions a Mac to its desired configuration and keeps it there. Provisioning is idempotent: safe to run on a fresh machine or an existing one, and re-running is the update path.

## Language

**App**:
Software this repo installs and manages on a Mac — GUI apps (casks) as well as CLI tools (formulas), plus the few that Homebrew doesn't carry and that install with their own script (Oh My Zsh).
_Avoid_: package; cask/formula when the whole is meant

**Present**:
An app already installed on the machine, by any means — Homebrew or manually. Provisioning only installs apps that are not present; an app is never treated as absent just because Homebrew does not manage it.
_Avoid_: installed (ambiguous: brew-managed vs on-disk) — say present when the distinction matters

**Agents VM**:
The one isolated OrbStack Linux machine this repo can provision (`agents`, Ubuntu 24.04) — it runs Hermes Agent and OpenCode, the two agents that do work for you. It is opt-in behind a bootstrap question (default No; `PROVISION_AGENTS_VM` pre-answers it), and answering yes also installs/updates OrbStack itself — neither is part of the Mac baseline. Reachable by SSH from the Mac, NATed behind it (no IP of its own on the LAN).
_Avoid_: container (it is a machine with services); sandbox (sounds like throwaway)

**Workspace**:
The single Mac folder (`~/agent_workspaces`) shared into the agents VM as `/workspace` — where repos live for both agents and the only Mac files they can see.
_Avoid_: home directory (the VM's own /home is not shared); mount (implementation detail)
