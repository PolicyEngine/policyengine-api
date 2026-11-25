# Stage 10 V2 Policy Deployment

This runbook applies the reviewed v2 policy schema, activates native v2 policy
resources, and optionally requires immediate v1-to-v2 mirroring. V1 reads and
integer identifiers remain in Cloud SQL throughout this stage.

## Preconditions

1. Stage 9 metadata catalogs must be initialized for the v2-supported US and UK
   and the running PolicyEngine.py version. Policy creation does not fall back
   to v1 metadata or another catalog version.
2. The runtime Supabase URL and target identity settings must identify the same
   reviewed project and require TLS. Use either the direct endpoint or
   Supavisor session mode on port 5432. The runtime rejects transaction-pooling
   endpoints on port 6543 because they cannot apply the per-session statement
   timeout.
3. Before applying the Phase 10 revisions beginning with `711ec2f0a5a5`, run the dormant-table qualification
   against the exact migration target:

   ```bash
   V2_MIGRATION_DATABASE_URL="postgresql+psycopg://..." \
   V2_SUPABASE_PROJECT_REF="reviewed-project-reference" \
   V2_SUPABASE_ENVIRONMENT="staging" \
   python scripts/qualify_v2_policy_migration.py
   ```

   Continue only when the result reports zero policies, policy-owned parameter
   values, and user-policy associations requiring preservation. A nonzero count
   requires a separate preservation decision.
4. Staging must use independently writable copies of both production databases.
   The staging Supabase project reference, Cloud SQL instance connection name,
   v1 password secret, and v2 runtime URL secret must all differ from their
   production values. The staging Cloud Run runtime identity must not have
   access to either production database secret.

The repository-level `PRODUCTION_*` variables record non-secret production
identities for comparison. The `staging`, `staging-database`, `production`, and
`production-database` GitHub environments supply their own target identities
and credential-resource names. The deployment and migration scripts stop
before connecting when the selected environment is missing or a staging value
equals its production counterpart.

## Schemas Before Traffic

Apply both generated revisions before deploying code that can enable immediate
v1 saved-policy mirroring. The MySQL revision adds the source revision and
ordered event records; the PostgreSQL revision adds the destination's last
applied source revision.

```bash
ALEMBIC_DATABASE_URL="mysql+pymysql://..." \
uv run alembic -c alembic-v1.ini upgrade head
```

```bash
V2_MIGRATION_DATABASE_URL="postgresql+psycopg://..." \
V2_SUPABASE_PROJECT_REF="reviewed-project-reference" \
V2_SUPABASE_ENVIRONMENT="staging" \
uv run alembic -c alembic-v2.ini upgrade head
```

Run each Alembic `check` command against the same corresponding target and
confirm no metadata/schema difference. The relevant generated revisions are
`3d6e8f553ca5` for MySQL and `af34023a728f` for the current PostgreSQL head.

The release workflow applies and verifies both staging schemas before building
the staging candidate. It replaces, rather than appends to, the candidate's
Cloud SQL attachment and verifies the deployed revision's Cloud SQL attachment,
database identity environment variables, route implementation settings, and
database read/write settings. It runs the normal deployed integration checks and
promotes the exact tested staging revision before production schema jobs become
eligible. A separate Python integration job tests policy and saved-policy
mirroring against disposable MySQL and PostgreSQL databases.

## Activation

The GitHub `staging` and `production` environments must define all three Phase
10 deployment variables:

```text
ROUTE_IMPL_POLICY=flask_fallback
DB_READ_POLICY=cloud_sql
DB_WRITE_POLICY=cloud_sql
```

The deployment workflow passes these values to Cloud Run, rejects missing or
invalid values before deployment, and verifies the exact values on the tagged
candidate revision before testing or promotion. These initial values do not
activate native policy readiness or v1 mirroring.

Native `/v2/policies` and `/v2/user-policies` routes use only the server-side
Supabase connection. The routes are registered as preview resources;
`ROUTE_IMPL_POLICY=fastapi_native` declares them operational for deployment
readiness validation without moving v1 routes away from Flask.

Stage 12A update: `/v2/user-policies` now requires a signed-in user's bearer
token, takes the owner from the token (requests no longer carry `user_id`),
accepts `legacy_policy_id`, and returns 409 for rows maintained by this mirror.
See `docs/migration/stage-12a-user-login.md`.

Native user-policy requests use an existing `users.id` UUID. V1 saved-policy
mirroring keeps the opaque Cloud SQL user identifier out of that foreign-key
column: `legacy_user_mappings` maps the exact v1 string one-to-one to a v2 user
UUID. First use creates a minimal v2 user and mapping in the same Supabase
transaction as the association; later saves and retries reuse that UUID.
`first_name`, `last_name`, and `email` are null for these transition-created
users because the v1 saved-policy record does not supply them. This stage does
not add or infer Auth0 identifiers.

Keep the initial v1 settings explicit:

```text
DB_READ_POLICY=cloud_sql
DB_WRITE_POLICY=cloud_sql
```

After native lifecycle checks pass, require immediate mirroring for US and UK
v1 policy and saved-policy mutations:

```text
DB_READ_POLICY=cloud_sql
DB_WRITE_POLICY=dual_write
```

The release workflow does not repeatedly change the staging write selection or
deploy a revision with deliberately invalid database credentials. Disposable
Python integration tests exercise successful writes, destination transaction
failure, retained-event processing, idempotent retries, and source/destination
rollback using the same MySQL and PostgreSQL engines as the deployed databases.

Under this selection, a core-policy mutation commits Cloud SQL first and then
completes its policy transaction in Supabase. The copy binds the v1 policy to
the running catalog whatever country package version the v1 row was saved
under (its stored `api_version`), the same way the Public API simulates an old
policy with the running country package. A policy is copied when every
parameter path it sets exists in the running catalog and its periods and values
are valid.

The copy splits off the v1 policy's model assumptions: every value under
`gov.simulation.`, plus `simulation.` in the US and `gov.dynamic.` in the UK
(`policyengine_api/dynamic_parameters.py`; UK `gov.dynamic.` joined on
C1 · 48's deploy). It stores them as a v2 dynamic,
hashed and deduplicated as a policy is, and keeps the rest in the v2 policy,
which is empty when the v1 policy set nothing else. Before looking up the
parameters it rewrites the UK's old spelling
`gov.simulation.labor_supply_responses.` to
`gov.simulation.labour_supply_responses.`, the only one the UK catalog has; a
v1 policy that sets one parameter under both spellings with different values
fails as `conflicting_values`. The mapping in `legacy_policy_mappings` names the
policy and the dynamic (`dynamic_id`), or no dynamic when the v1 policy sets no
assumptions. A v1 policy copied before the split existed keeps its copy: its
assumptions stay policy values and its mapping names no dynamic, and a UK
copy made before `gov.dynamic.` joined keeps those values in its policy too,
until the split command splits it (see "Splitting stored policies that hold
model assumptions" below). Native `POST /v2/policies` refuses such
values with 422 instead (code `dynamic_parameters`), and they are created
through `POST /v2/dynamics`.

A saved-policy mutation commits
its source row, incremented revision, and complete event in one Cloud SQL
transaction. The same request then processes that source's pending events in
revision order and records `processed_at` only after the corresponding
Supabase transaction commits.

Canada, Nigeria, and Israel remain supported by v1 but have no v2 catalog in
this phase. Their policy and saved-policy mutations continue using Cloud SQL
only under `DB_WRITE_POLICY=dual_write`: they create no v2 snapshot or mirror
event and do not access Supabase.

A failed copy does not fail the request. Whatever the cause (a Supabase
failure, a policy the v2 catalog cannot translate, or a missing catalog
version), the v1 write is already committed, the copy failure is logged with
its `failure_category`, and the route returns its normal v1 response. A
saved-policy event that failed stays pending, and the next mutation of the same
saved policy replays it, with earlier retained events first. A core policy
whose copy failed is copied again the next time any request writes the same
policy. A core policy that already has a copy returns that copy without being
translated again, so writing it again after a PolicyEngine.py or country
package upgrade does not fail. When two first copies of the same v1 policy run
at once on revisions with different PolicyEngine.py versions, the mapping
committed first is the copy; the other request's v2 policy commits without a
mapping and its record reports `policy_created=false`. Destination revision and fingerprint checks make a replay safe if
Supabase committed but the Cloud SQL processing marker did not. There is no
background processor or reconciliation process.

The v2 runtime applies one five-second value to pool acquisition, PostgreSQL
connection establishment, and each SQL statement. The API does not retry these
operations internally. Native v2 routes return a secret-safe HTTP 503 for a
timeout or other SQLAlchemy database failure so the caller can retry the
complete request. v1 mirroring logs the same failure and returns the v1
response.

Browser preflight requests are handled by the outer ASGI CORS middleware before
FastAPI or Flask route resolution. It permits the public HTTP methods and
request headers used by v1 and v2, exposes `X-PolicyEngine-Request-Id`, and
applies CORS headers to typed errors and service-unavailable responses. Route
functions do not implement separate preflight behavior.

## Missing parameters

A policy can set parameters that a later country package release renamed or
removed. Policy reads report them as `missing_parameters`, so a client can
tell its user and not run the policy:

- `GET /{country}/policy/{policy_id}` checks the v1 policy's parameter paths
  against the leaf parameters of the country model the Public API runs. It
  reads nothing from Supabase, so v1 reads stay on Cloud SQL. The field is
  null for a stored policy that is not a parameter-path object.
- `GET /v2/policies/{policy_id}`, `GET /v2/policies` and `POST /v2/policies`
  check each policy against the catalog of the running PolicyEngine.py
  version. The field is null when that catalog is not published.

Both use the comparison the v2 copy uses (`parameters_missing_from_model`),
and the v2 catalog of a release holds the same leaf parameters as that
release's country model. So a v1 policy reported with missing parameters
is one a first copy under the running release refuses as
`missing_parameters`. A policy copied before a release removed its
parameter keeps that copy, since an existing copy is not translated again;
it is still reported as missing on both routes.

## Monitoring

Monitor structured events with metric names `v1_policy_mirror_operations` and
`v1_user_policy_mirror_operations`. Alert on `outcome=error`, grouped by
`failure_category` and country. Each failed copy also records a fixed
`failure_reason`:

| `failure_category` | `failure_reason` |
| --- | --- |
| `catalog_or_translation` | `missing_parameters` (the policy sets a parameter the running catalog lacks), `invalid_parameter_values`, `empty_parameter_values`, `invalid_period`, `conflicting_values`, `too_many_values` (more than 1,000 dated values), `catalog_absent` (no catalog for the running PolicyEngine.py version), `catalog_query_failed`, `catalog_version_not_found`, `catalog_mismatch` |
| `integrity` | `mapping_conflict`, `content_hash_collision` (of the policy or the dynamic), `stored_policy_integrity`, `stored_dynamic_integrity`, `saved_policy_integrity` (any integrity check of a saved-policy copy) |
| `database` | `database_error` |
| `configuration` | `configuration` |
| `unexpected` | `missing_reform_policy` (a saved policy's v1 reform could not be loaded), `unexpected` |
| `missing_mirror_snapshot`, `missing_mirror_revision` | the same value as the category |

Events include the legacy integer ID,
destination UUID when committed (a policy copy's record also names its
dynamic's, `destination_dynamic_id`, and whether it created it,
`dynamic_created`), attempted and completed database sources, and
duration. They do not include policy JSON, presentation data, database URLs, or
credentials.

The disposable and route-level tests verify that:

- native policy and association create/read/list/update/delete operations use
  the initialized catalog and Supabase only;
- both newly created and existing v1 policies receive durable mappings,
  including existing policies saved under an older country package version;
- v1 saved-policy label updates change association `name`, while v1-only field
  updates change only the mapping fingerprint;
- saved-policy event revisions are processed in ascending order, successful
  events have `processed_at`, and failed events retain a null `processed_at`;
- all v1 reads continue to query Cloud SQL and all v1 responses retain integer
  IDs without v2 UUIDs.

## Application Rollback

Set `DB_WRITE_POLICY=cloud_sql`, or route traffic to a prior application
revision whose environment selects it, to stop copying. v1 mutations then open
no Supabase connection and record no saved-policy events. A failed copy does
not fail a v1 mutation under `dual_write`, so copy failures on their own are
handled from the `outcome=error` records, not by rolling back. Application
revisions built before that change return HTTP 503 for a failed copy; do not
route traffic to one whose environment selects `DB_WRITE_POLICY=dual_write`.
Keep `DB_READ_POLICY=cloud_sql`. Do not delete policies, associations, or
mappings already committed in Supabase; they remain valid for later retries.

Application rollback does not automatically downgrade either additive source
schema or the v2 schema. If a schema downgrade is separately approved, first
disable native policy traffic and mirroring, verify that no pending Cloud SQL
events or retained v2 data depend on the revisions, and run the reviewed
Alembic downgrades against their confirmed database targets.

The normal staging promotion still restores the previously serving Cloud Run
revision when promotion or the stable-URL health check fails. It does not
create persistent policy fixtures or change the configured write selection as
part of each release.

## Removal of the v1 saved-policy routes

`POST /{country_id}/user-policy`, `GET /{country_id}/user-policy/{user_id}`
and `PUT /{country_id}/user-policy` are removed, along with
`GET /{country_id}/policies`. Only legacy.policyengine.org called them; Cloud
Run request logs for the 30 days to 2026-10-19 showed no saved-policy
requests. No new v1 saved policies are created, so none are copied to v2. The
saved-policy copying and v1 saved-policy service modules stay until dual-write
is deleted, and existing Cloud SQL `user_policies` rows are kept.

The Public API also no longer serves Canada, Nigeria and Israel: their v1
policy requests are rejected as unknown countries before any write, so every
v1 policy write is now for a country that v2 supports.

## Splitting stored policies that hold model assumptions

`scripts/split_v2_policy_copies.py` (C1 · 48, run as the operator step C1 · 49)
splits every stored v2 policy that sets a model assumption: a parameter under
`gov.simulation.`, US `simulation.` or UK `gov.dynamic.`
(`policyengine_api/dynamic_parameters.py`). The v1-to-v2 copy made such
policies before it split model assumptions off, and for UK `gov.dynamic.`
values until that prefix joined; a v1 policy is never copied again. C1 · 50's
revision, which moves dynamic parameters into their own tables, refuses to
run while any policy value names one, because the foreign key's cascade would
otherwise change those policies silently.

For each such policy, in one transaction, the command
(`policyengine_api/services/v2/policy_copy_split/services.py`) locks the
legacy mappings and saved policies that name it, then the policy itself
(`SELECT … FOR UPDATE`, so nothing can start naming it meanwhile), in the
order API v1's copy of a v1 saved policy takes the same locks, so the two
wait for each other instead of deadlocking. Its lock waits end after half a
second, shorter than PostgreSQL's default one-second `deadlock_timeout`, so
in any other lock cycle with a live write, such as API v1's sign-in merge
(which locks a browser's user, then moves its saved policies), the split's
wait ends first: it rolls back that copy and tries it again, up to five
times a second apart, and the live write goes ahead. It then:

- finds or creates a policy holding the values that aren't model assumptions,
  empty when there are none, and a dynamic holding the model assumptions,
  both on the copy's own catalog version, with the same parameter IDs, values
  and dates, through the services `POST /v2/policies` and `POST /v2/dynamics`
  store them with;
- points each `legacy_policy_mappings` row that names the copy at that policy
  and dynamic. A mapping that already names a dynamic (a UK copy made after
  C1 · 36 holding `gov.dynamic.` values) gets one dynamic holding that
  dynamic's values and the copy's model assumptions together; the earlier
  dynamic is kept;
- points each `user_policies` row that names the copy at that policy, keeping
  its name, description, `baseline` and `provenance`, and gives its owner a `user_dynamics` row
  with the saved policy's name and no description, naming the dynamic the
  saved policy's own v1 policy's mapping now names, or else the copy's
  dynamic. When the owner already has a saved dynamic in that country naming
  the same dynamic with the same name (two null names count as the same),
  that one is reused;
- deletes the copy, and its values with it, once nothing names it.

A copy that a `simulations`, `reports` or `household_jobs` row names is
split and its mappings and saved policies are re-pointed, but the copy is
kept: those rows' keys hash the policy, and their `policy_id` is `ON DELETE
SET NULL`, so deleting the copy would silently make them current law. A copy
whose mapping's dynamic sets one of its model assumptions for the same start
date differently, is bound to another catalog version, or would hold more
than 1,000 values together with it, is refused, and nothing changes for it.
The user decided these cases on 2026-11-25.

Running the command again changes nothing: a re-pointed mapping or saved
policy no longer names the copy, and the policy and dynamic are found by
their content hashes. A kept copy is listed as kept again, and a refused
copy as refused.

### Deploy order

1. API v1's release containing C1 · 48 (and so C1 · 36 and C1 · 43) deploys
   in the environment, so the v1-to-v2 copy there splits UK `gov.dynamic.`
   values too and no new policy holding model assumptions is stored.
2. C1 · 49 runs the command there: the read-only listing, then `--apply`,
   then the listing again. That listing lists nothing and exits with 0, or
   lists only kept and refused copies and exits with 1. Each of those still
   holds model assumptions as policy values, so the operator settles it by
   hand first (for example by deleting the test simulations, reports or
   household calculations that name it), with the user's approval.
3. Only then, once a listing lists nothing, does C1 · 50's revision run in
   that environment.

### The temporary role

The command connects as `policyengine_v2_policy_copy_split`, which holds only
the grants `POLICY_COPY_SPLIT_PRIVILEGES` declares
(`policyengine_api/data/v2/privileges.py`; a test checks the statements below
match it). No deploy grants, checks or reports the role. Create it in the
environment's v2 database, as a login that may grant on the migration role's
tables, with a SCRAM-SHA-256 verifier made locally in place of the password,
so the database never receives the password itself. Each block is one
statement, so `supabase db query` takes it in one call:

```sql
DO $$
BEGIN
  CREATE ROLE policyengine_v2_policy_copy_split LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD '<SCRAM-SHA-256 verifier>';
  GRANT USAGE ON SCHEMA public TO policyengine_v2_policy_copy_split;
  GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE public.policies TO policyengine_v2_policy_copy_split;
  GRANT INSERT, SELECT ON TABLE public.dynamics TO policyengine_v2_policy_copy_split;
  GRANT INSERT, SELECT ON TABLE public.parameter_values TO policyengine_v2_policy_copy_split;
  GRANT INSERT, SELECT ON TABLE public.user_dynamics TO policyengine_v2_policy_copy_split;
  GRANT SELECT ON TABLE public.household_jobs TO policyengine_v2_policy_copy_split;
  GRANT SELECT ON TABLE public.parameters TO policyengine_v2_policy_copy_split;
  GRANT SELECT ON TABLE public.reports TO policyengine_v2_policy_copy_split;
  GRANT SELECT ON TABLE public.simulations TO policyengine_v2_policy_copy_split;
  GRANT SELECT ON TABLE public.tax_benefit_model_versions TO policyengine_v2_policy_copy_split;
  GRANT SELECT, UPDATE ON TABLE public.legacy_policy_mappings TO policyengine_v2_policy_copy_split;
  GRANT SELECT, UPDATE ON TABLE public.user_policies TO policyengine_v2_policy_copy_split;
END
$$;
```

Deleting a policy needs no privilege on `parameter_values`: PostgreSQL runs a
foreign key's cascade as the table's owner. After the run, revoke each grant
and drop the role, as the login that created it. `DROP OWNED BY` would need
the role's own privileges, which a login that isn't a superuser lacks on
PostgreSQL 16 and later, so each grant is revoked by name:

```sql
DO $$
BEGIN
  REVOKE ALL ON TABLE public.dynamics FROM policyengine_v2_policy_copy_split;
  REVOKE ALL ON TABLE public.household_jobs FROM policyengine_v2_policy_copy_split;
  REVOKE ALL ON TABLE public.legacy_policy_mappings FROM policyengine_v2_policy_copy_split;
  REVOKE ALL ON TABLE public.parameter_values FROM policyengine_v2_policy_copy_split;
  REVOKE ALL ON TABLE public.parameters FROM policyengine_v2_policy_copy_split;
  REVOKE ALL ON TABLE public.policies FROM policyengine_v2_policy_copy_split;
  REVOKE ALL ON TABLE public.reports FROM policyengine_v2_policy_copy_split;
  REVOKE ALL ON TABLE public.simulations FROM policyengine_v2_policy_copy_split;
  REVOKE ALL ON TABLE public.tax_benefit_model_versions FROM policyengine_v2_policy_copy_split;
  REVOKE ALL ON TABLE public.user_dynamics FROM policyengine_v2_policy_copy_split;
  REVOKE ALL ON TABLE public.user_policies FROM policyengine_v2_policy_copy_split;
  REVOKE USAGE ON SCHEMA public FROM policyengine_v2_policy_copy_split;
  DROP ROLE policyengine_v2_policy_copy_split;
END
$$;
```

### Running it

From a checkout of the deployed release, with three variables set in the
shell for the run only:

- `V2_POLICY_COPY_SPLIT_DATABASE_URL`: the temporary role's
  `postgresql+psycopg://` URL with `sslmode=require` (or `verify-ca` or
  `verify-full`), on the project's direct host or its pooler in session
  mode on port 5432. Transaction mode (port 6543) is refused, because it
  doesn't keep the command's timeouts;
- `V2_SUPABASE_PROJECT_REF` and `V2_SUPABASE_ENVIRONMENT`: the values of the
  GitHub Actions environment variables of the same names, which the command
  checks the URL against.

```bash
uv run --frozen python scripts/split_v2_policy_copies.py
uv run --frozen python scripts/split_v2_policy_copies.py --apply
```

Without `--apply`, every transaction is `READ ONLY`, and the command lists
for each copy the policy and dynamic it would point at (by ID when stored,
otherwise by content hash), each legacy mapping (country and v1 policy ID,
with the dynamic it named before) and saved policy it would re-point, each
saved dynamic it would add or reuse, and whether the copy would be deleted,
kept (with how many simulations, reports and household calculations name it)
or refused (with the reason). With `--apply` it reports the same with the IDs
of the rows it points at or creates, as each copy's transaction commits. It
prints no URL, saved-policy name or user ID.

The listing reports a row that an earlier copy in the same run would create
as reused, since `--apply` commits each copy before the next.

It exits with 0 when no stored policy sets a model assumption afterwards (for
the listing: when every listed copy would be deleted), and with 1 otherwise.
Missing settings, a failed connection, or a copy that still can't get its
locks after five attempts raise, and also exit with 1; the copies already
reported have committed, and running the command again carries on. The
command adds a 10-second connection timeout, a half-second lock timeout and
a 60-second statement timeout to the URL.
