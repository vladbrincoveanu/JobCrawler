# JobCrawler

Project-level instructions for Claude Code working in this repo.

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

1. `~/.claude/CLAUDE.md` — global cross-project rules
2. `CLAUDE.md` (this file) — project-level instructions
3. `.claude/CLAUDE.md` — local skills + rules inventory
4. `.claude/rules/*.md` — domain rules (loaded for matching scopes)

To add a domain rule, drop a markdown file in `.claude/rules/` with a clear scope header.

## See also

- `AGENTS.md` — cross-tool agent instructions (keep in sync)
- `README.md` — user-facing project description
