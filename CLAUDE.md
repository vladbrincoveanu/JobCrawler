# JobCrawler

Project-level instructions for Claude Code working in this repo.

## Rules

Bias: caution over speed on non-trivial work. Use judgment on trivial tasks.

1. **Think before coding** — state assumptions; ask if uncertain; flag simpler alternatives; stop when confused.
2. **Simplicity first** — minimum code for the problem; no speculative features/abstractions.
3. **Surgical changes** — touch only what's needed; don't refactor or "improve" adjacent code.
4. **Goal-driven execution** — define success criteria, loop until verified, don't just follow steps.
5. **Model for judgment calls only** — classification/drafting/summarization/extraction, not routing/retries/deterministic transforms.
6. **Token budgets are not advisory** — 4k/task, 30k/session; surface breaches, don't silently overrun.
7. **Surface conflicts, don't average them** — pick the more recent/tested pattern, explain why, flag the other for cleanup.
8. **Read before you write** — check exports, callers, shared utilities before adding code.
9. **Tests verify intent, not just behavior** — a test that can't fail when business logic changes is wrong.
10. **Checkpoint after every significant step** — summarize done/verified/left; don't continue from an unclear state.
11. **Match codebase conventions, even if you disagree** — surface concerns, don't fork silently.
12. **Fail loud** — "completed"/"tests pass" is wrong if anything was skipped silently.

Relentless execution mode is active in this project by default (run tasks end-to-end without approval pauses, subject to the hard no-go list: never delete user-authored files, never push to `main`, never spend money, never touch secrets, never skip safety rails). Branch work under `relentless/<slug>` per the Conventions section below.

## Project overview

> ⚠️ TODO — fill in once product scope is defined.
> One-paragraph summary of what JobCrawler does, who it's for, and what problem it solves.

## Stack

> ⚠️ TODO — list languages, frameworks, services, data stores.

## Directory layout

- `.claude/` — Claude Code skills, rules, per-project config
  - `CLAUDE.md` — skill inventory + project rules
  - `rules/` — domain-specific rules (e.g. `ui-testing.md`)
  - `skills/` — local skills
- `graphify-out/` — generated knowledge graph (gitignored, regenerable)

> ⚠️ TODO — add app directories once they exist (`dashboard/`, `api/`, etc.).

## Commands

> ⚠️ TODO — once `package.json` / `pyproject.toml` exist, document `install`, `dev`, `build`, `test`, `lint`.

## Conventions

- **Branch:** `relentless/<slug>` for in-progress work; `main` reserved for reviewed merges.
- **Commits:** Conventional Commits (`type: subject`).
- **Secrets:** never commit `.env`, `*.local`, `secrets/`, credentials.
- **Generated artifacts:** stay out of git (see `.gitignore`).
- **Auto-commit:** milestones commit on the relentless branch without prompting.

## Per-project Claude config

Claude Code reads these files in order:

1. `CLAUDE.md` (this file) — project-level instructions, self-contained
2. `.claude/CLAUDE.md` — local skills + rules inventory
3. `.claude/rules/*.md` — domain rules (loaded for matching scopes)

To add a domain rule, drop a markdown file in `.claude/rules/` with a clear scope header.

## See also

- `AGENTS.md` — cross-tool agent instructions (keep in sync)
- `README.md` — user-facing project description
