# API Route Query Contracts

Read this guidance before adding an HTTP route or changing the query-parameter
contract of an existing route.

## Scope

Every new route that accepts query parameters must define them through the
repository's shared typed query-parameter mechanism. When a change adds,
removes, renames, or changes the meaning of a query parameter on an existing
route, migrate that route's complete query contract to the shared mechanism as
part of the same change.

Do not refactor an unrelated existing route merely because another part of its
module changes. This rule applies when the route is new or its public query
contract changes.

## Canonical Parameter Meanings

The framework-neutral source is `policyengine_api/query_parameters.py`.
Resource query models compose `CountryQuery`, `CatalogQuery`,
`PaginationQuery`, and the canonical annotated field types defined there.
FastAPI routes obtain dependencies through
`policyengine_api/fastapi_routes/query_parameters.py::query_dependency`.
Flask routes use `parse_multidict_query` when a reviewed legacy query contract
is migrated. Route modules must not reproduce these adapters.

Reuse the shared definition whenever a query field has an established meaning.
The definition owns all of the following behavior:

- public parameter name;
- Python and OpenAPI types;
- normalization and coercion;
- required or optional status;
- default value;
- length, numeric, enumeration, and collection bounds;
- scalar or list multiplicity;
- validation error semantics.

Country, PolicyEngine.py version, pagination, UUID resource filters, and other
repeated filter concepts must not be redefined independently in route modules.
A resource-specific query schema should compose canonical fields and add only
filters whose meaning is specific to that resource.

`country_id` is required only when the resource contract is country-scoped. Do
not add it to a route that has no country-dependent behavior merely for visual
uniformity.

## Parsing Rules

- Reject unknown query parameters rather than ignoring misspellings.
- Reject a scalar query parameter supplied more than once rather than selecting
  an arbitrary value.
- Accept repeated keys only when the canonical field is explicitly list-valued.
- Keep query, path, and request-body fields in their documented locations; do
  not move an identifier between them to reuse a schema.
- Do not maintain a second manual parser with different defaults or coercion.
- Do not copy parsing behavior from a legacy route when it conflicts with the
  canonical typed definition.

FastAPI routes should consume composed query schemas as typed dependencies so
the runtime validation and generated OpenAPI schema have the same source. A
Flask route whose query contract changes should use a thin adapter from
`request.args` into the same canonical schema rather than calling `get`,
`json.loads`, `int`, or similar coercion independently for each field.

The Phase 10 policy schemas demonstrate the required composition:

- `PolicyCreateQuery` for policy creation;
- `PolicyDetailQuery` for country-scoped policy detail;
- `PolicyCollectionQuery` for exact model filtering and pagination;
- `CountryQuery` for association create, detail, update, and delete;
- `UserPolicyCollectionQuery` for association user/policy filtering and
  pagination.

## Compatibility and Documentation

Changing a query parameter's name, type, default, bounds, multiplicity, or
normalization changes the public route contract. Preserve existing behavior
unless the change explicitly authorizes a contract revision. For API v2
migration routes, also read `migration_contracts.md` and update the migration
registry, workflow contracts, generated documentation, and stable OpenAPI
fields when applicable.

The route's OpenAPI operation must expose every accepted query field with the
same required status, type, default, and bounds enforced at runtime. Do not
document query parameters accepted only by an untyped fallback parser.

## CORS Preflight Requests

The outer ASGI application owns cross-origin request handling through
Starlette's `CORSMiddleware`. Do not add resource-specific `OPTIONS` operations
or CORS headers to FastAPI route functions. A browser preflight contains
`Origin` and `Access-Control-Request-Method`; the middleware must answer it
before resource routing, including when the eventual resource method is
`POST`, `PATCH`, or `DELETE`. An ordinary `OPTIONS` request without those
headers continues through normal route resolution.

When a new public HTTP method or request header is added, verify that the
application-level CORS configuration permits it. Tests must cover the
preflight response and an error response, and browser-readable response
headers must be included in `Access-Control-Expose-Headers` when applicable.

## Required Verification

For each new or changed query contract, cover the applicable cases:

- required parameters are absent;
- optional parameters use their canonical defaults;
- valid values receive canonical normalization;
- invalid types and out-of-range values are rejected;
- unknown parameters are rejected;
- duplicate scalar parameters are rejected;
- explicitly list-valued parameters accept the documented repeated form;
- OpenAPI declares the runtime name, type, required status, default, and bounds;
- parameters reused by multiple routes behave identically.

Use `docs/engineering/skills/testing.md` to select the appropriate test layer
and commands. Route behavior that changes a migration contract also requires
the focused migration checks documented in `migration_contracts.md`.
