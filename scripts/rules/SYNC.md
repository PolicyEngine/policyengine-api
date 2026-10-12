# Keeping `scripts/rules/` in sync

This directory is byte-identical in two repositories:

- `PolicyEngine/policyengine-api` (canonical copy)
- `PolicyEngine/policyengine-sim-api`

When you change it:

1. Make the change in policyengine-api first.
2. Copy the whole directory to policyengine-sim-api unchanged.
3. Bump `TOOL_VERSION` in `__init__.py`, and `tool_version` in each repository's
   `rules/registry.toml`.
4. Run `python -m scripts.rules render` in both repositories. The header of
   `docs/generated/rules.md` shows a hash of the tool's source, so reviewers can
   confirm both copies match.

Repository-specific content belongs in `rules/registry.toml`, never in this
directory.
