# Stage 8 managed Redis topology

## Decision

Stage 8 will use **Google Cloud Memorystore for Redis** in `us-central1`, the
same region as the production and staging Cloud Run services. Each deployed
environment receives its own instance and credentials:

| Environment | Instance ID | Tier | Capacity | Redis version |
| --- | --- | --- | --- | --- |
| Staging | `policyengine-api-cache-staging` | Basic | 1 GiB | 7.2 |
| Production | `policyengine-api-cache-prod` | Standard HA | 5 GiB | 7.2 |

Production uses Standard Tier's cross-zone replica and automatic failover
because Redis coordinates expensive work in addition to caching completed
results. Staging uses Basic Tier to keep the validation environment
independent at lower cost. Neither environment enables read replicas.
Capacity is an initial allocation, not a durable-data commitment; metrics and
eviction pressure may justify resizing it later.

Memorystore for Redis is preferred over Memorystore for Redis Cluster or
Memorystore for Valkey for this stage. The existing consumers use ordinary
Redis commands and require multi-key atomic operations. A single-instance
Redis-compatible endpoint preserves those semantics without introducing hash
slot constraints or a cluster-aware client during the SQLite-to-cache
migration.

Google documents [Memorystore for Redis tiers and pricing][pricing], the
[supported Redis versions and creation flags][create], and direct Cloud Run
[connectivity to Memorystore][cloud-run-redis].

## Network and transport

Both instances use all of the following settings:

- the existing `default` VPC in the `policyengine-api` Google Cloud project;
- the `policyengine-api-memorystore-psa` automatically allocated `/24` Private
  Service Access range and
  `PRIVATE_SERVICE_ACCESS` connection mode;
- Redis AUTH enabled;
- in-transit encryption set to `SERVER_AUTHENTICATION`; and
- no public endpoint, localhost fallback, or container-launched Redis server.

Cloud Run revisions will use [Direct VPC egress][direct-vpc] through the
`default` `us-central1` subnet with `private-ranges-only` routing. Direct VPC
egress avoids a permanently provisioned Serverless VPC Access connector while
keeping ordinary internet-bound traffic on its current path. The deployment
must account for Cloud Run subnet address consumption and connection resets;
the runtime client therefore needs bounded pools, timeouts, and reconnect
behavior.

Stage 8 enables the Memorystore and service-networking APIs, creates the
non-overlapping allocation and both instances, and validates
TLS-authenticated access from more than one Cloud Run instance before rollout.

## Authentication and secret boundaries

The authenticated URL and all currently downloadable instance CAs are stored
in separate Secret Manager secrets:

| Environment | URL secret | CA secret |
| --- | --- | --- |
| Staging | `policyengine-api-staging-runtime-cache-url` | `policyengine-api-staging-runtime-cache-ca` |
| Production | `policyengine-api-prod-runtime-cache-url` | `policyengine-api-prod-runtime-cache-ca` |

They are exposed only to the Cloud Run and App Engine runtime identities for
that environment. Staging and
production must not share an endpoint or credential. Endpoint, port, expected
TLS mode, and environment are explicit deployed settings; application code
must not infer them from v1 database configuration or fall back to localhost.

The client validates the Memorystore server certificate using in-memory
`ssl_ca_data` and Google's documented instance-specific certificate-authority
material. CA rotation requires storing every currently downloadable CA in the
CA secret before Google rotates the serving certificate. Secret-bearing URLs, AUTH values,
and certificate material must never be logged, committed, or placed in image
layers.

## Namespace and loss semantics

Every key is namespaced by environment, service, cache family, and cache
schema version. Result keys additionally include every result-affecting input
and relevant package version. This is defense in depth around the physically
separate instances and permits schema transitions without interpreting old
payloads as current.

Redis remains disposable:

- missing, expired, evicted, flushed, incompatible, or unreadable completed
  results are cache misses and may be recomputed from durable sources;
- completed-result writes subtract a random zero-to-ten-percent interval from
  each cache family's nominal TTL to spread normal expirations without
  exceeding the configured maximum age;
- coordination and claim TTLs remain exact because they establish safety
  bounds for work ownership;
- a failed completed-result cache write does not turn successful computation
  into failure; and
- coordination and claim failures fail closed so multiple instances do not
  silently duplicate guarded expensive work.

No report, report run, household, policy, output, or other durable domain
record may exist only in Redis.

## Revision rollout and rollback

Managed-cache configuration is revision-specific. A revision cannot receive
traffic unless its environment's endpoint, AUTH secret, TLS configuration,
and VPC attachment are valid. New Stage 8 revisions use managed Redis only;
they never start or select an embedded Redis process.

The immediately preceding application revision retains its own prior runtime
configuration. Rolling back means moving Cloud Run traffic to that known-good
revision. It does not copy, restore, or downgrade cache contents. The managed
cache may be retained or flushed because cache loss is handled as a miss, and
the dormant v2 Postgres schema remains in place unless an operator separately
invokes a reviewed migration downgrade.

If a rollout requires incompatible cache serialization, the new revision uses
a new cache-schema namespace. During a traffic split, old and new revisions
may therefore coexist without either revision reading the other's incompatible
values.

[cloud-run-redis]: https://cloud.google.com/memorystore/docs/redis/connect-redis-instance-cloud-run
[create]: https://cloud.google.com/memorystore/docs/redis/create-manage-instances
[direct-vpc]: https://cloud.google.com/run/docs/configuring/vpc-direct-vpc
[pricing]: https://cloud.google.com/memorystore/docs/redis/pricing
