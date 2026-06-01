# Claude Instructions

These instructions apply repository-wide.

## Canonical Guidance

Repository-wide AI-facing engineering guidance lives in `AGENTS.md`.
Canonical skills live under `docs/engineering/skills/`.

Use those files as the source of truth. This file is a Claude adapter and should
stay thin; do not duplicate detailed testing, CI, formatting, or architecture
rules here.

## Required Skill Lookup

Before opening, replacing, or sharing a PR, read
`docs/engineering/skills/github-prs.md`.

When changing API v2 migration contracts, route-group migration metadata,
generated migration docs, or migration guard scripts, read
`docs/engineering/skills/migration_contracts.md`.

When adding, moving, or reviewing tests, read
`docs/engineering/skills/testing.md`.

## Safety Boundaries

Do not claim a route, database table, compute path, or deployment surface has
migrated unless the relevant contract tests, migration flags, and generated
migration docs identify that state.
