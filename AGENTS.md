## Commit messages

This repo is 100% agent-coded (see README) — keep that attribution greppable in git history. End every commit message with a trailer line naming the harness and model(s) that produced it:

    Generated with opencode — model(s): <exact id(s), comma-separated if more than one>

List every model used in the session, including subagents; use the exact model id from your context. If you are not running in opencode, name that harness instead.

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `flungster/mac-setup`, driven with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary; each label string is identical to its role name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` at the repo root, ADRs under `docs/adr/`. See `docs/agents/domain.md`.
