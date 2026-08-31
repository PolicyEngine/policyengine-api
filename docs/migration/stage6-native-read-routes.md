# Stage 6 Native Read Routes

Stage 6 moves low-risk, read-only API v1 routes from the mounted Flask
application to native FastAPI handlers. Both implementations remain in the
same Cloud Run image so each migrated group has a configuration-only fallback.

## Route groups

| Selector | Native routes | Fallback |
| --- | --- | --- |
| `ROUTE_IMPL_HEALTH` | `/liveness-check`, `/readiness-check` | Existing Flask handlers |
| `ROUTE_IMPL_SPECIFICATION` | `/specification` | Existing Flask handler |
| `ROUTE_IMPL_METADATA` | `/{country_id}/metadata` | Existing Flask blueprint |

The accepted values are `fastapi_native` and `flask_fallback`. The selectors
are ordinary GitHub environment variables, not secrets. A Cloud Run deployment
requires all three explicitly and verifies their values on the exact candidate
revision before promotion. Invalid values prevent the application from
starting. Local execution defaults to Flask fallback when the selectors are
absent.

`/health` and `/simulation-gateway-check` remain native under both health
settings because they were already FastAPI routes before Stage 6 and have no
Flask predecessor. The root route and every non-migrated API route continue to
use the mounted Flask application.

## Compatibility contract

- Liveness and readiness retain their existing status codes, plain-text bodies,
  and readiness-state source.
- The specification uses the same loaded document as Flask.
- Metadata retains its existing JSON envelope, serialization, country ordering,
  invalid-country response, and gzip behavior for large responses.
- Request IDs, reflected CORS, and migration logging apply to both
  implementations.
- Migration logs record the implementation that actually served the request,
  rather than merely echoing a configured default.

Stage 6 does not change database access, schemas, simulation routing,
authentication, public hostnames, or supported countries.

## Qualification and release

The standard release workflow deploys a tagged, no-traffic staging candidate.
Before staging promotion it:

1. verifies the selector values on the exact candidate revision;
2. runs the complete Cloud Run staging integration suite.

Only the exact tested staging revision is promoted. Production then deploys
automatically, repeats candidate identity and read-route smoke checks, and
promotes the exact tested production revision. Immediate promotion or stable
health failure restores the previously serving revision.

## Rollback

For a later route-specific regression, change the affected selector to
`flask_fallback` in both GitHub environments and run the normal
staging-to-production release. The other groups can remain native. Do not
change DNS, Cloud Run traffic percentages, database configuration, or the
Simulation Entrypoint for this rollback.

Before the Stage 6 release is merged, both environments must contain:

```text
ROUTE_IMPL_HEALTH=fastapi_native
ROUTE_IMPL_SPECIFICATION=fastapi_native
ROUTE_IMPL_METADATA=fastapi_native
```

Record the tested staging and production revision names, the production
observation window, and any rollback action in the tracking issue or pull
request.
