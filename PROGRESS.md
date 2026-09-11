# Progress: Fable review fixes on PR #3827 (canonical SPM API)

## State

Worktree `policyengine-api-canonical-current-master-20260910`, branch
`max/spm-api-current-master-20260910` (PR #3827's remote head branch is
`max/canonical-spm-api-20260909`; both pointed at `50d1f0c9` at start).

## Done

- Verified clean worktree at `50d1f0c95da1206c17fc59ce1fc2f345bbfe3e5e`.
- Merged `origin/master` (`d36a2081`) as a merge commit. No conflicts. The only
  `uv.lock` delta is master's two `spm-calculator` declaration lines; the
  reviewed runtime tuple is unchanged.
- `uv sync --frozen --extra dev` succeeds; `spm-calculator 0.3.1` now installed,
  bundle still legacy (`_legacy_bundle` true, `spm_metadata('us').available`
  false, `simulation_supports_spm` false).

## Next

- Baseline full unit/contract run in CI order.
- Medium 1: stop failing closed on uncertified bundles for callers sending no
  SPM settings.
- Medium 2: decide and document the no-geography contract under a certified
  bundle.
- Medium 3: make the household-trace cache tolerate omitted nulls, and stop a
  country receipt shape change turning a completed calculation into a 500.
- Lows 1, 2, 5; evaluate 3 and 4.
