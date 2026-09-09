# Canonical SPM household API contract

This contract is enabled only by an installed, certified US bundle that pins its
SPM forecast hash/scenario and supports the country `spm` constructor. This change
does not select a new released model or promote a deployment. US bundles 5.2.0
and 5.3.0 with model 1.764.6 retain their existing behavior when settings are omitted and reject
explicit SPM settings. Uncertified future US bundles fail closed. Other countries
retain their behavior and reject US-only SPM settings.

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

Tax-only calculations can use periods outside the artifact's measurement years,
including a valid metro selection, without generating SPM receipts. When an SPM
dependency actually executes for an unsupported year, the API returns a structured
failure with the calculator's typed `SPM_YEAR_UNAVAILABLE` code. The API preserves
typed input errors and does not reclassify unrelated or untyped `ValueError`s.

## Storage, replay and responses

`POST /us/household` and `PUT /us/household/{id}` accept `spm` beside `data`.
`GET /us/household/{id}` returns it in `result.spm`, beside `household_json`.
The database stores the resolved selection atomically in the existing household
JSON and includes it in the household hash. Settings are removed from the entity
input object before calculation. Ordinary edits that omit `spm` retain a saved
choice. Once a certified bundle is active, all US households linked to simulations
have immutable inputs and SPM selections, including historical households without
saved `spm`. Changing inputs or adding or changing a selection requires a new
household; its label may still be edited. A label-only edit leaves historical
inputs, saved settings, hashes and model versions unchanged. The web app already
uses that replacement workflow. This keeps simulation/report IDs tied to their
original measurement and inputs without rewriting saved inputs or a schema
migration.

`GET /us/household/{id}/policy/{policy_id}` replays the stored selection under the
selected policy. No independent simulation-level override is supported. Top-level
`spm` on simulation POST/PATCH is rejected instead of silently ignored.

Successful canonical calculations add `spm_config` and `spm_provenance` beside
`result`. Provenance comes from the actual simulation and includes artifact,
scenario, years, geography, composition/storage methods and runtime versions.
It remains in JSON form through stored replay and cache hits. A tax-only receipt
may have empty `years` and `geographies` because no SPM measurement was requested.
Clients saving simulation outputs must retain this full response envelope.

`POST /us/simulation` takes `population_id`, `population_type` (`household` or
`geography`) and integer `policy_id`. It creates a pending record (HTTP 201) or
returns an existing record with its saved status/output (HTTP 200); it does not
run a calculation. Household simulations use the linked household's selection.

US household references consisting entirely of ASCII digits share one numeric
identity across simulation lookup, household edit protection and comparison
report linkage. For example, historical `"00001"` and new `"1"` can form a
comparison report, while each saved simulation and report input keeps its own
spelling. Suffixes, decimals, signs, whitespace and Unicode digits do not create
numeric aliases. Under a certified bundle, all linked US households allow label
changes; changing their inputs or adding or changing an SPM selection requires a
new household, including when the linked household has no saved `spm`.

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
household/tracer cache uses schema version 2, includes the selection in identity,
and stores settings/provenance atomically with the result and trace. Missing or
mismatched canonical receipts are cache misses.

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

## Economy worker selection

Both `GET /us/economy/{policy_id}/over/{baseline_policy_id}` and its
`/budget-window` counterpart accept `spm` as one URL-encoded JSON object in the
query string. For example, before URL encoding:

```text
/us/economy/123/over/456?region=us&time_period=2026&spm={"geography_kind":"national"}
/us/economy/123/over/456/budget-window?region=us&start_year=2026&window_size=2&spm={"geography_kind":"national"}
```

Use the client's query-encoding support to encode that JSON once. All query
parameters are scalar: repeated keys, unknown parameters, malformed JSON and
duplicate fields inside the SPM object return HTTP 400. `region` is required;
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
through asynchronous submission and polling.

See the [canonical SPM worker PR](https://github.com/PolicyEngine/policyengine-sim-api/pull/677)
for the implemented worker paths and remaining coordinated release gates.


Partial selections preserve omitted fields in JSON; omissions inherit the certified
bundle defaults. The selection schema deliberately supplies no wire defaults,
so generated clients preserve that distinction. Resolved settings freeze all six
fields. Responses may omit null geography_id/as_of values, but must include every
non-null resolved field; receipt replay never substitutes current defaults.
