# Progress: Fable review fixes on PR #3827 (canonical SPM API)

## State

Worktree `policyengine-api-canonical-current-master-20260910`, local branch
`max/spm-api-current-master-20260910`. PR #3827's remote head branch is
`max/canonical-spm-api-20260909`; both pointed at `50d1f0c9` at start. There is
no remote branch named `max/spm-api-current-master-20260910`, so the push target
is `max/canonical-spm-api-20260909` with the same `50d1f0c9` lease.

## Done

- Verified clean worktree at `50d1f0c95da1206c17fc59ce1fc2f345bbfe3e5e`.
- Merged `origin/master` (`d36a2081`, carrying PR #3824 `2a967658`) as a merge
  commit. No conflicts. The only `uv.lock` delta is master's two
  `spm-calculator` declaration lines; the reviewed runtime tuple is unchanged.
- `uv sync --frozen --extra dev` succeeds; `spm-calculator 0.3.1` installed,
  bundle still legacy (`measurements` absent, `_installed_country_implements_spm`
  false, `spm_metadata('us').available` false, `normalize_spm_selection('us',
  None)` returns None).
- **Medium 1** — the legacy/certified boundary is decided by the installed
  country model's capability, never a bundle version allowlist; the remaining
  fail-closed case also fails `/readiness-check`.
- **Medium 3** — one shared rule (`spm.resolved_spm_settings`) compares receipt
  settings for the trace cache and the worker path, and an unreadable country
  receipt is a typed configuration failure rather than a 500.
- **Medium 2** — a measurement is chosen by the request or by the household a
  replay reads it from; an inherited bundle default is not a choice, so its
  dependants come back null instead of rejecting the request. `POST
  /us/household` stores a selection only when the caller sent one, so hashes and
  response shapes do not move when a bundle is certified. Committed in
  `docs/canonical-spm.md` under "Choosing a measurement, or not".
- **Low 1** — an explicit `"spm": null` is rejected on the v1 routes, matching
  the v2 document validator and the simulation routes.
- **Low 2** — a saved artifact hash this deployment lacks is
  `SPM_CONFIGURATION_UNAVAILABLE` on replay rather than `SPM_SETTINGS_INVALID`;
  SPM messages no longer quote pydantic internals or its documentation URL.
- **Low 3** — removed the linked-household `FOR UPDATE` read from simulation
  creation.
- **Low 5** — an uncertifiable stored economy result records a terminal error on
  both the annual and budget-window paths, so polling ends.

## Next

- Low 4 (repeated settings resolution and worker-capability fetches) stays an
  accepted follow-up: the per-poll capability fetch is the safety gate that
  detects a worker redeploy mid-run, and caching it would open a window where
  the API certifies a bundle the worker no longer serves.
