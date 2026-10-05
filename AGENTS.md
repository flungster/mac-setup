## Commit messages

This repo is 100% agent-coded (see README) — keep that attribution greppable in git history. End every commit message with a trailer line naming the harness and model(s) that produced it:

    Generated with opencode — model(s): <exact id(s), comma-separated if more than one>

OpenCode runs different models in its stages (here: Claude Opus plans, Qwen 3.8 — reported as `brain` in its context — builds). List every model that contributed to the change: one id per contributing stage or subagent, each exactly as its own context reports it. A feature planned by one model and built by another carries both:

    Generated with opencode — model(s): claude-opus-5-5, brain

If you are not running in opencode, name that harness instead.

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `flungster/mac-setup`, driven with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary; each label string is identical to its role name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` at the repo root, ADRs under `docs/adr/`. See `docs/agents/domain.md`.
