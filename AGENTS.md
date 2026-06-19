# JobCrawler — Agent Instructions

Tool-agnostic instructions for any AI coding agent (Claude Code, Codex, Copilot, Gemini CLI, Cursor) operating in this repo.

## Project

> ⚠️ TODO — one-paragraph description. What does JobCrawler do?

## Setup

> ⚠️ TODO — install steps once `package.json` / `pyproject.toml` exists.

## Run / build / test

> ⚠️ TODO — list the primary commands once they exist.

## Conventions

- **Conventional Commits** — `type: subject` (feat, fix, chore, docs, refactor, test, perf, build, ci).
- **No secrets in git** — `.env`, `*.local`, `secrets/`, and credentials stay local.
- **Generated artifacts** are gitignored (`graphify-out/`, `.next/`, `dist/`, `build/`).
- **Branches** — work on `relentless/<slug>`; reserve `main` for reviewed merges.
- **No destructive cleanup** — never `rm -rf` user-authored files; rename to `.deleted-<ts>` instead.

## Where to look

| File | Purpose |
|------|---------|
| `README.md` | User-facing description, status, quickstart |
| `CLAUDE.md` | Claude-Code-specific notes (skill + rule inventory) |
| `.claude/` | Claude skills + project rules |
| `AGENTS.md` (this file) | Cross-tool agent instructions |

## Sync with `CLAUDE.md`

This file is intentionally parallel to `CLAUDE.md`. If you change project-level guidance in one, mirror it in the other — Claude Code reads `CLAUDE.md`; Codex / Copilot / others read `AGENTS.md`.

## Hard no-go (for autonomous agents)

- Never `git push` to `main`/`master`.
- Never commit secrets or modify `.env`.
- Never delete user-authored files without explicit instruction.
- Never spend money / call paid APIs without explicit instruction.
- Never skip verification before declaring done.
