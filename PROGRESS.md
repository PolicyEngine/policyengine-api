# Fable final findings — PR3827 — 2026-09-09

## State

- Starting head: `a00f59430da22d4944a49efb95a91c9d9ea1d013`; reviewed base: `37e168a907f37d5dea0d4ae6e9284ebc15a3d5af`.
- Authorized scope: fix the final three Fable findings, verify, commit each coherent step, push PR3827, and write `rollout/api-fable-fixes/FINAL-REPORT.md`.
- Preserve all historical reports and the four R3 MySQL-qualified identity source files. Prior 110 real MySQL tests and 504 calculator equivalence cases remain prior evidence, not new runs.
- No merge, deployment, browser/population jobs, sibling source edits, or `.err` / `.lane.log` reads. Release qualification and the next Fable gate remain coordinator-owned.

## Done

- Inspected the worktree, exact starting commit, complete Fable review, and repository route/testing/PR/migration standards.
- Attempted upstream fetch before edits; CLI DNS failed. GitHub connector verified PR3827 is draft/open at the supplied head/base and branch `max/canonical-spm-api-20260909`.
- Confirmed the existing HTTP polling regression deliberately retains dead jobs, matching the review finding.
- Findings 2/3 complete: documented all linked US household immutability under certification, tested historical spm-less input/settings rejection plus label/replacement/history preservation, and verified the public worker PR677 link. New documentation regression: 1 failed / 1 passed before correction; focused documentation/household suites: 81 passed. Four protected runtime identity files are unchanged.
- Finding 1 complete: annual/window typed poll failures persist terminal code/message, clear dead worker handles, preserve shared-cache identity, and replay after service recreation. Eight HTTP/segmented regressions failed before implementation; focused lifecycle/cache/retry verification passed 167 tests. Independent local source review found no additional defect.
- Broad focused routes/cache/worker/identity/SPM suite passed 576 tests with 37 dependency-gated skips. Contract/OpenAPI suite passed 76 tests. An initial in-progress test run hit a newly added fixture keyword typo; it was fixed and the entire focused group rerun successfully.
- Configured mypy passed (54 files); migration guards/export passed (11 workflows / 43 requests), without generated drift. Repository formatting and changed-test Ruff lint passed before this commit.

## Next

- Finish authenticated installed-source verification and final source binding; publish verified commits to the PR through the working GitHub connector, verify exact message/head/body, and write the final report.
- Preserve the 110-case real-MySQL and 504-case calculator evidence as prior runs. Release qualification and final-head Fable remain coordinator gates.

---

The following historical progress is preserved verbatim from the prior untracked report. Its lane-specific instructions and status describe earlier work, not this continuation.

# Canonical SPM API integration

## Final review fixes (R3) — 2026-09-09

### State

- All three R3 findings are fixed and validated. HEAD remains coordinator-committed R2 snapshot `03927cafd88489a17d57d6ab5da68aa224c2ba2b`; upstream base remains `37e168a907f37d5dea0d4ae6e9284ebc15a3d5af`.
- Own the two identity/linkage defects and requested simulation OpenAPI completeness. Preserve earlier reports and root-owned capability/adjacent sources; no commits, push, deployment or browser work.
- The independent MySQL lane owns its harness, database and profile. This lane uses only existing in-memory tests and will supply final source hashes.

### Done

- Read the final independent review and repository route/testing guidance.
- Delegated regression-first household immutability and persisted comparison-report tests, plus simulation OpenAPI declarations.
- Reproduced both P2 defects and the missing simulation declarations before fixes.
- Shared strict US ASCII numeric household canonicalization and SQL matching across all three consumers, preserving saved spellings and exact historical replay. Opaque US household IDs use byte-exact SQL equality.
- Actual Flask report POST/replay/GET now persists the complete historical-baseline/new-reform specification and `ReportOutputRun` snapshot. Actual HTTP household tests cover unrelated IDs, genuine aliases and label-only edits.
- Served Flask/native OpenAPI now documents simulation POST/PATCH/GET, SPM restrictions and stored output envelopes; added actual HTTP/schema regressions and current docs.
- Combined changed/affected suites passed: 281 passed, 2 skipped. Focused red/green evidence is retained for the final report.
- Final schema review corrected ignored `api_version` values and scalar-string output documentation; four actual HTTP/ORM regressions failed before correction. Final OpenAPI/report services: 69 passed.
- Remaining contract/native metadata tests: 25 passed. Final real country/calculator overlay with identity, report persistence and receipts: 76 passed, including both prior skips.
- All eight changed/new Python files pass Ruff; all 387 repository Python files pass formatting. Guards/export retain 11 workflows/43 requests with no generated diff; diff checks pass.
- Wrote `API-SPM-REVIEW-FIXES-R3.md` with exact tests, source hashes and qualification limits. The five relevant overlay source hashes still match R2; no commits were created.
- Final verification confirmed all 169 API source hashes and five overlay hashes unchanged, with protected capability/tests and generated contracts unchanged from HEAD.

### Next

- Coordinator: rerun independent MySQL qualification on the recorded final hashes and complete separate package/release gates. The bounded R3 source fixes, tests and documentation are complete.

## Typed-year follow-up (R2) — 2026-09-09

### State

- Use the calculator's committed lazy provider boundary (`fd7de4b3b670a10acd72567904ccea800252c9a5`) and preserve typed `SPM_YEAR_UNAVAILABLE` throughout the API.
- Prior findings 2–6 implementation/report remains preserved; the coordinator owns the capability function and its tests. No commits, push, deployment, browser or sibling edits.

### Done

- Removed private traceback/code-object/error-text matching from API error recognition.
- Retained explicit typed-year API/worker whitelists and real household/axes expectations; updated the direct forecast regression to prove untyped errors stay untouched.
- Updated current client docs to require the typed year boundary; delegated focused worker HTTP polling coverage and receipt/identity inspection.
- Added four actual worker-client → Flask → service/cache polling regressions for annual/window requests and HTTP 400/422; repeated polls retain the typed year error without success caching or replacement jobs.
- Final R2 combined suites: 579 passed, 37 skipped. Real country/calculator overlay plus identity/receipt replay: 139 passed. All five recorded source hashes stayed unchanged during validation.
- No new API defects found in bounded receipt/model metadata inspection. Ruff lint passed for 25 changed Python files; all 382 Python files passed formatting. Migration guards/export and diff checks passed with no generated-contract changes.
- Wrote `API-SPM-REVIEW-FIXES-R2.md` with exact commands, findings dispositions, source/installed metadata distinctions and qualification limits.

### Next

- Coordinator: complete released-package/artifact, deployed-worker, managed-cache, MySQL and staging qualification. The bounded API R2 implementation and validation are complete; no commits were created.

## Independent review fixes — 2026-09-09

### State

- This lane owns findings 2–6 and the review's defensive improvements. The coordinator owns finding 1 (`get_spm_capability` and its separate tests); those edits are excluded here.
- Preserve existing dirty work and frozen calculator/country/wrapper/worker sources. Use the existing pins interpreter and explicit development source overlays; no release qualification claim.
- No commits, push, deployment, browser use, or heavy microsimulation, following the task-specific instruction over the standing commit order.

### Done

- Read the independent review and repository route/testing guidance; inspected failing API paths.
- Assigned parallel work for typed economy queries/docs, failed-job replay, and historical identity/cache integrity.
- Regression-first failures reproduced: 10 real-country HTTP year/laziness cases, 11 malformed worker shapes, historical alias and corrupt-cache cases, and canonical/legacy repeated failed polls.
- Implemented lazy missing-year error conversion at the API boundary; removed eager metro calculation-period validation. The frozen country has no SPMValidationError; the calculator exposes SPMInputError but emits a plain missing-year ValueError for national/metro selection.
- Worker validation now requires object results, positive integer window sizes, annual row objects/calendar years, and rejects windows where an annual result is required.
- Failed-job replay passed 136 focused tests; historical identity/cache plus relevant existing suites passed 86 tests (2 skipped); real source-overlay household-cache receipts passed 11 tests.
- Typed economy query parsing and OpenAPI/metadata/legacy documentation are complete. Both HTTP routes reject malformed/duplicate/unknown query values and preserve selection omissions.
- Combined regression suite: 557 passed, 37 skipped. Real country/calculator overlay settings/country suite: 96 passed. Final economy query/legacy budget-route check: 60 passed. Shared query mypy, repository Ruff format check (381 files), changed-Python lint and migration guards/export passed; generated migration contracts remained unchanged.
- Final overlay recheck detected an external calculator change: the provider now emits typed `SPM_YEAR_UNAVAILABLE`. Added API and worker forwarding for that code while retaining the narrow earlier-calculator fallback. Rerunning the combined and real-source suites against the current snapshot; no sibling edits were made by this lane.

### Next

- Finish current-snapshot source-overlay/combined checks and complete `API-SPM-REVIEW-FIXES.md`.
- Coordinator retains finding 1 and all release, deployed-worker, managed-cache and MySQL qualification gates.

## State

- Isolated worktree based on locally recorded origin/master `37e168a907f37d5dea0d4ae6e9284ebc15a3d5af`. Root fetched live upstream on 2026-09-09; HEAD...FETCH_HEAD was independently verified as 0/0.
- Independent Git source clone under the task workspace avoids modifying the dirty original checkout or protective pin worktree.
- No commits, push, deployment or publication, following the task-specific instruction over the standing commit order.
- Country/model release and final rollout gates remain coordinator-owned; dependency pins will not be invented or promoted.

## Done

- Inspected original dirty API checkout and read global/repository guidance and policyengine-api skill.
- Inspected public wrapper settings and country `spm` interface.
- Delegated scoped app request-flow work to an isolated checkout.
- Implemented typed SPM selection, pinned-artifact validation, metadata availability and fail-closed handling of uncertified future bundles; no dependency pins changed.
- Carried resolved settings through request identity, stored household JSON/hash, reform replay, and versioned atomic result/tracer/provenance caches.
- Added structured 400 handling for geography-required, geography-unavailable and composition-required errors, including dependent calculations and axes.
- Preserved linked canonical household inputs/selection by requiring a new household for edits after simulation linkage; coordinated row locks prevent linking/edit races.
- Completed the worker audit, then replaced the protective rejection with capability-validated support during the new worker integration. Settings now reach annual/window workers and economy cache identity; returned/cached receipts are checked and typed polling errors remain 400s.
- Initial existing household regression groups passed (24 and 16 tests); 33 new API request/storage/replay/cache tests passed. Worker/service/route regression group passed 232 tests.
- Actual canonical source-overlay API tests exposed an upstream metro error conversion gap; the API validates explicit area selection and requested years against the artifact.
- Completed actual canonical API integration: 70 tests passed across focused runs, including real full-output national calculation and stored replay/cache with positive SPM threshold and year provenance.
- Final overlapping legacy group: 135 passed, 19 canonical-only cases skipped; worker/metadata/identity/migration contract group: 282 passed.
- Scoped app: 201 tests across 18 suites passed, Vite build/lint/format passed. Full Next/typecheck blocked by inherited missing dependencies; app handoff records exact details.
- Wrote API-CANONICAL-SPM-HANDOFF.md with public contract, worktree isolation, actual model evidence, app file groups and remaining release gates.
- Aligned public OpenAPI with generated typed SPM settings/provenance, all household paths and compatible validation responses; fixed mixed YAML response-key serialization in the public loader.
- Final specification/identity/household/simulation/cache regression group: 57 passed. Final repository formatting, changed-Python Ruff lint, migration guard and diff whitespace checks all passed.
- Rechecked original API dirty state and original clean app state: both match inspection; neither source checkout was edited.

## Next

- Coordinator: certify/release the exact country/wrapper/worker bundle, materialize locked app/client-generator dependencies, audit external household clients, complete browser/end-to-end checks, and run final rollout gates. See the new worker handoff.

- Continuation: 135 canonical source-overlay API tests passed; 131 passed/21 skipped in the overlapping legacy group; app 201 tests rerun and passed.
