# Canonical SPM household API contract

This contract is enabled only by an installed, certified US bundle that pins its
SPM forecast hash/scenario and supports the country `spm` constructor. This change
does not select a new released model or promote a deployment.

Whether a bundle predates this contract is decided by the installed country
model's capability, never by a bundle version string; the automated bundle update
moves those strings for unrelated countries and patch releases, and an allowlist
of known versions would turn a routine release into a rejection of every US
request. A bundle whose US model does not implement the `spm` constructor retains
its existing behavior when settings are omitted and rejects explicit SPM settings
with `SPM_SETTINGS_UNSUPPORTED`, whatever its version. A bundle whose US model
does implement the constructor but ships no certified `measurements.spm`
configuration fails closed with `SPM_CONFIGURATION_UNAVAILABLE`: such a
deployment also fails `/readiness-check`, so the condition is reported where the
release is gated rather than only on each request. Other countries retain their
behavior and reject US-only SPM settings.

## Selecting a measurement

`GET /us/metadata` exposes `result.spm.available`. When true, `settings_schema`
is the public Pydantic schema and `defaults` contains the certified selection.
Clients must offer an explicit local/national choice before running SPM-dependent
household calculations. The web app requires that choice when support is
available. An omitted API choice does not infer national geography.

The `spm` object accepts only these fields:

| Field | Meaning |
| --- | --- |
| `forecast_content_sha256` | Optional expected hash; if supplied must equal the bundle's independently pinned artifact. |
| `scenario` | A scenario in that artifact; omission uses the certified default. |
| `geography_kind` | `county` (default), `national`, or `metro`. |
| `geography_id` | Required for `metro`; forbidden for `county` and `national`. |
| `county_vintage` | `"2020"`. |
| `as_of` | Optional information-date constraint accepted by the artifact. |

Unknown fields and invalid selections are rejected. Only the household's
`county_fips` input identifies a local county. Computed county, state, first county
in state and congressional district do not identify an SPM area. The full
canonical artifact supplies 2022–2035 measurements; no consumer CPI extrapolation
or congressional-district geographic factors are introduced.

`POST /us/calculate` and `/us/calculate-full` take settings beside the existing
household and policy objects:

```json
{
  "household": {
    "people": {"you": {"age": {"2026": 40}}},
    "households": {"household": {"members": ["you"], "state_code": {"2026": "CA"}}},
    "spm_units": {"unit": {"members": ["you"], "spm_unit_spm_threshold": {"2026": null}}}
  },
  "policy": {},
  "spm": {"geography_kind": "national"}
}
```

National is an explicit request, not a fallback for a missing county. A tax-only
request does not need geography or composition solely to construct a simulation
or read its provenance. SPM-dependent requests validate the required primitives
when the country calculates them. `/calculate-full` and stored household replay
request the full output set, which includes SPM dependencies.

### Choosing a measurement, or not

A measurement is chosen by a request that sends `spm`, or by the household whose
saved selection a replay reads. Omitting `spm` inherits the certified bundle's
defaults to construct the simulation but chooses nothing, and the two cases
differ in exactly one way:

- **A chosen measurement whose primitives are missing is a request error.** No
  county and no explicit geography, or no classified SPM adult, returns the typed
  400 below rather than a result with holes in it. The caller asked for this
  measurement, so the API does not quietly decline to compute it.
- **An inherited default is not a choice, so its dependants are merely
  unavailable.** Variables that need the missing primitive come back null, the
  way any other variable the model cannot compute does, and the rest of the
  calculation is returned normally with HTTP 200. An axes request spells that
  null as a correctly sized array of nulls beside a response warning, as it does
  for every other variable it cannot calculate.

Certifying a bundle therefore never makes an existing or newly created household
uncalculable. A state-only household saved before certification, with no saved
`spm`, still replays under any policy through
`GET /us/household/{id}/policy/{policy_id}` and through `/calculate-full`; its
SPM-dependent variables are null. This is the commitment clients may rely on: a
missing SPM primitive never turns a request that chose nothing into a 400.

The certified boundary itself is the exception, and it is deliberate. A bundle
whose measurement configuration this build cannot resolve — no certified
configuration for a model that implements the constructor, a manifest this API
cannot read, or an artifact that will not load — fails every US calculation with
a configuration code, whatever the caller sent, and also fails
`/readiness-check`: it is meant to stop a deployment rather than to be met on a
request. `GET /us/metadata` still answers, reporting `spm.available` false.

A country receipt this API cannot read in full is the same class of failure and
carries the same code, but it is found only on a calculation that produced a
receipt: readiness resolves settings and never constructs a simulation, so it
cannot report that one ahead of the requests. Whichever of them fails, the
message names the offending field and reason; no SPM message quotes validator
internals or their documentation URL, wherever the settings came from.

`POST /us/household` stores a selection only when the caller sent one. A
household created without `spm` keeps the household hash, the stored JSON and the
`GET /us/household/{id}` response shape it would have had before certification,
and its replay chooses nothing. Certification is still validated on that request,
so a bundle this build cannot serve is rejected; only the resolved defaults it
would have produced are left unwritten, because storing them would record a
choice the caller never made and make the household's own replay assert it.

An explicit `"spm": null` is not an omission. `POST /us/household`,
`/us/calculate` and `/us/calculate-full` reject it with `SPM_SETTINGS_INVALID`,
matching the v2 document validator and the simulation routes; omit the field to
inherit the certified defaults. On any other country the same routes reject an
`spm` key at all, null included, with `SPM_SETTINGS_UNSUPPORTED`, as
`POST /{country}/simulation` already did: there is no shape of it to correct.

Tax-only calculations can use periods outside the artifact's measurement years,
including a valid metro selection, without generating SPM receipts. When an SPM
dependency actually executes for an unsupported year, a request that chose the
measurement returns a structured failure with the calculator's typed
`SPM_YEAR_UNAVAILABLE` code; a request that chose nothing leaves that year's
dependants null like any other missing primitive, under the rule above. The API
preserves typed input errors and does not reclassify unrelated or untyped
`ValueError`s.

## Storage, replay and responses

`POST /us/household` accepts `spm` beside `data`.
`GET /us/household/{id}` returns it in `result.spm`, beside `household_json`.
When the caller sends one, the database stores the resolved selection atomically
in the existing household JSON and includes it in the household hash; a request
that sends none stores none, as above. Settings are removed from the entity
input object before calculation. All stored households are immutable, including
historical households without saved `spm` and households without a simulation.
`PUT /us/household/{id}` is unsupported and returns HTTP 405. Changing inputs,
labels or an SPM selection requires creating a new household. Clients should send
the saved `spm` when creating a replacement that keeps the same measurement.
The original household, simulations and reports retain their inputs, selection,
hash and model version.

When Stage11 household dual writes are selected, the same source transaction
retains a create event containing the household's stored selection, complete and
resolved when the caller sent one and absent when it did not. The v2 translation
preserves that saved selection in `household_data.spm` and includes it in
canonical household identity. It does not resolve the selection against
current bundle defaults. Historical documents without `spm` retain their
existing shape and identity. Household inputs and SPM settings use existing JSON
storage; no additional schema migration is required.

`GET /us/household/{id}/policy/{policy_id}` replays the stored selection under the
selected policy. No independent simulation-level override is supported. Top-level
`spm` on simulation POST/PATCH is rejected instead of silently ignored.

Successful canonical calculations add `spm_config` and `spm_provenance` beside
`result`. A receipt describes the measurement the simulation was constructed
with, not a guarantee that every SPM-dependent variable produced a value: a
calculation that never chose a measurement still carries the inherited one's
receipt beside its null cells. Read the values to learn which of them a
measurement produced. Provenance comes from the actual simulation and includes artifact,
scenario, years, geography, composition/storage methods and runtime versions.
It remains in JSON form through stored replay and cache hits. A tax-only receipt
may have empty `years` and `geographies` because no SPM measurement was requested.
Clients saving simulation outputs must retain this full response envelope.

`POST /us/simulation` takes `population_id`, `population_type` (`household` or
`geography`) and integer `policy_id`. It creates a pending record (HTTP 201) or
returns an existing record with its saved status/output (HTTP 200); it does not
run a calculation. Household simulations use the linked household's selection.

US household references consisting entirely of ASCII digits share one numeric
identity across simulation lookup and comparison report linkage. For example, historical `"00001"` and new `"1"` can form a
comparison report, while each saved simulation and report input keeps its own
spelling. Suffixes, decimals, signs, whitespace and Unicode digits do not create
numeric aliases. Household immutability applies regardless of simulation linkage,
country, certification, or whether the household has saved `spm`.

`PATCH /us/simulation` identifies the record with body `id` and accepts `status`
(`pending`, `complete` or `error`), `output` and `error_message`. At least one
update field must be non-null, and `complete` requires non-null `output`. Store
the full calculation envelope inside `output`, including its `spm_config` and
`spm_provenance`. A JSON-encoded output string is also accepted. This endpoint
stores the supplied output; it does not validate SPM receipt integrity. Null
update fields are ignored. The legacy `api_version` input is ignored; writes
record the installed country model version. Top-level `spm`, even null, returns
HTTP 400 `SPM_SETTINGS_UNSUPPORTED` on POST and PATCH.

POST, PATCH and `GET /us/simulation/{id}` return the simulation record inside
`result`. Non-string JSON `output` and `simulation_spec_json` are returned as
JSON-encoded strings, or null when absent. Stored scalar strings are returned
unchanged. Decode a saved household `output` envelope once to recover the
calculation result and SPM receipts. `active_run_id` identifies a pending/running
run and becomes null when
inactive; `latest_successful_run_id` identifies the latest successful run. These
run fields and specification metadata may be null on historical records. The
served `/specification` documents these request and response shapes through both
Flask and the native specification route.

HTTP response cache identity includes the normalized selection and model/bundle
versions, and validates certification before reading the cache. The stored
calculated-household cache uses schema version 2, includes the selection in
identity, and stores settings/provenance atomically with the result and its
warnings. Missing or mismatched canonical receipts are cache misses.

## Errors

SPM input failures return HTTP 400 in the existing validation envelope:

```json
{
  "status": "error",
  "message": "A county, explicit area, or national selection is required",
  "result": null,
  "errors": [{"code": "SPM_GEOGRAPHY_REQUIRED", "message": "A county, explicit area, or national selection is required"}]
}
```

`SPM_GEOGRAPHY_REQUIRED` indicates missing explicit geography for an SPM
dependency; `SPM_GEOGRAPHY_UNAVAILABLE` indicates malformed/unknown county or area;
`SPM_COMPOSITION_REQUIRED` indicates no classified SPM adult. Country error text
is retained. `SPM_YEAR_UNAVAILABLE` indicates an unsupported measurement year.
Settings errors use `SPM_SETTINGS_INVALID`,
`SPM_SETTINGS_UNSUPPORTED`, or `SPM_CONFIGURATION_UNAVAILABLE`.

A stored household whose saved artifact hash is not the installed one returns
`SPM_CONFIGURATION_UNAVAILABLE` on replay, not `SPM_SETTINGS_INVALID`: the saved
selection is that household's identity rather than something this caller got
wrong, and the deployment is what cannot serve it. The same mismatch sent in a
request is still `SPM_SETTINGS_INVALID`. Error messages never quote validator
internals; a rejected selection reports the offending field and reason only.

## Economy worker selection

Both `GET /us/economy/{policy_id}/over/{baseline_policy_id}` and its
`/budget-window` counterpart accept `spm` as one URL-encoded JSON object in the
query string. For example, before URL encoding:

```text
/us/economy/123/over/456?region=us&time_period=2026&spm={"geography_kind":"national"}
/us/economy/123/over/456/budget-window?region=us&start_year=2026&window_size=2&spm={"geography_kind":"national"}
```

Use the client's query-encoding support to encode that JSON once. All query
parameters are scalar: repeated declared keys, malformed JSON and duplicate or
unknown fields inside the SPM object return HTTP 400. Query parameters the route does
not declare are ignored, as the legacy routes always did; an omitted or
misspelled `spm` therefore inherits the certified default measurement. `region` is required;
annual requests require `time_period`, while budget-window requests require
`start_year` and `window_size` (1–75, ending no later than 2099). Years use four
digits. Optional fields are `dataset` (default `default`), `version` (installed
country model version), `target` (`general`, or annual-only `cliff`), and the
deprecated no-op boolean `include_district_breakdowns`. Omitted `spm` inherits
certified bundle defaults. The served `/specification` generates these query
declarations from the same typed models as the Flask parser.

Before cache access or submission,
the API validates the selected worker application's `canonical-spm-v1` capability
from `/versions`, including agreement with the bundle's independently pinned
artifact hash. An old or uncertified worker returns `SPM_CONFIGURATION_UNAVAILABLE`.

Normalized settings are sent to both annual and budget-window jobs and participate
in economy cache identity. Results carry `spm_config` and `spm_provenance` with
`baseline` and `reform` receipt lists (one per executed regional segment). Each
budget-window annual row carries these fields; annual results expose them inside
`result`, and budget-window results inside `result.annualImpacts`. Stored results require matching
settings and valid receipts. Typed SPM input errors remain structured 400s
through asynchronous submission and polling. Poll-time typed failures retain
their code and message for the existing cache lifetime. Later reads replay that
failure after API service restarts without polling or resubmitting the failed
job. Canonical cache identity and runtime-bundle refresh rules still apply.

See the [canonical SPM worker PR](https://github.com/PolicyEngine/policyengine-sim-api/pull/677)
for the implemented worker paths and remaining coordinated release gates.


Partial selections preserve omitted fields in JSON; omissions inherit the certified
bundle defaults. The selection schema deliberately supplies no wire defaults,
so generated clients preserve that distinction. Resolved settings freeze all six
fields. Responses may omit null geography_id/as_of values, but must include every
non-null resolved field; receipt replay never substitutes current defaults.


## Economy deployment checks and cache transitions

Deployment alignment validates the installed wrapper version and the runtime's
manifest-selected version, then applies the request-time SPM capability and
forecast-hash checks to the registered bundle. Legacy bundles require bundle
registration but do not advertise canonical SPM. A canonical promotion must
coordinate the wrapper and calculator pins and pass qualification with their
published wheels; the legacy dependency tuple does not qualify that path.

Annual economy cache identities include the calculation target. Budget-window
identities include the resolved worker application before errors, completed
results, or running batch handles are read. The budget-window registry lookup
must succeed even for a cached response: a registry outage fails the request
rather than replaying an unverified predecessor's result. A replacement worker
receives a new cache key; the same worker's terminal error remains terminal.

The first deployment of these identities makes older economy cache entries
ineligible. Their ordinary expiry remains in place. Active jobs under the old
keys may finish, but requests under the new keys can submit replacement jobs;
account for this one-time recomputation window when scheduling promotion.

Both tagged Cloud Run candidates run a Utah current-law/current-law economy
probe without creating a policy. It requires zero budget change and, for a
canonical bundle, matching settings and baseline/reform forecast receipts.
National numerical acceptance remains a separate release qualification.
