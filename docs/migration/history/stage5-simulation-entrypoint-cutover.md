# Stage 5 Simulation Entrypoint Cutover Record

This is the auditable release record for moving API v1's outbound simulation
requests to the separate Cloud Run Simulation Entrypoint. The merge commit for
this record intentionally triggers the normal API v1 staging-to-production
release after the environment selector is changed.

## Scope

The cutover changes only the network path used by API v1 for simulation
submissions and polling:

```text
API v1 -> canonical Simulation Entrypoint -> Modal gateway -> Modal executor
```

It does not change API v1's public routes or response contracts, move
simulation compute or durable job state out of Modal, or migrate SQL-backed
application data. Direct Modal routing remains configured for rollback.

## Qualification completed before cutover

- The canonical entrypoint passed health, readiness, version, authentication,
  comparison, and one-year budget-window checks.
- Comparison and budget-window IDs were unchanged and pollable through both
  the canonical entrypoint and direct Modal, with identical completed payloads.
- `X-PolicyEngine-Request-ID` correlated requests from the canonical edge
  through the Cloud Run entry service, the Modal gateway, and the executor.
- Cloud Run used its own client-credentials identity for Modal rather than
  forwarding the API caller's bearer token.
- Three alternating paired runs per path put every canonical median latency
  and completion metric within the 20% migration gate; the largest measured
  canonical median increase was 9.4%.
- The standard Simulation API workflow completed its full staging integration
  suite before deploying, promoting, and verifying production and the
  canonical hostname.

## Release behavior

Immediately before this PR is merged, both API v1 GitHub environments must set
`SIM_ENTRYPOINT=cloud_run_simulation_entrypoint`. The qualified canonical URL
must remain present as the environment-scoped `SIMULATION_ENTRYPOINT_URL`
secret, and the direct Modal URL must remain available under
`OLD_SIMULATION_GATEWAY_URL`.

The normal API v1 workflow then owns the entire release:

1. Deploy staging with the Cloud Run selector.
2. Run the complete staging calculation, economy, and budget-window suite.
3. Block production on any staging failure.
4. Automatically deploy and verify production with the same selector.
5. Assign stable API v1 traffic to the exact tested production revision.

Production does not repeat the calculation suite already completed in the
production-equivalent staging environment.

## Rollback

For a later regression, restore both environment selectors to
`old_gateway_direct` and run the normal release workflow. Staging must again
pass before production returns to direct Modal. Do not change DNS or manually
adjust Cloud Run traffic percentages for this rollback.
