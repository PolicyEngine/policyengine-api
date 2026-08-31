# Stage 8 managed Redis topology

This document records the topology requirements without publishing concrete
project, region, network, instance, secret-resource, or service-account
identifiers. Operators must resolve those values from the approved deployment
configuration and secret-management surfaces.

## Decision

Stage 8 uses Google Cloud Memorystore for Redis in the reviewed deployment
region. Staging and production use separate instances and credentials:

| Environment | Topology requirement |
| --- | --- |
| Staging | Independent non-production instance sized for validation |
| Production | High-availability instance with automatic failover |

Production uses a cross-zone replica because Redis coordinates expensive work
in addition to caching completed results. Staging uses a lower-cost independent
topology. Neither environment enables read replicas. Capacity is an initial
operational allocation, not a durable-data commitment; metrics and eviction
pressure determine later resizing.

Memorystore for Redis is preferred over clustered alternatives for this stage.
The existing consumers use ordinary Redis commands and require multi-key atomic
operations. A single Redis-compatible endpoint preserves those semantics
without introducing hash-slot constraints or a cluster-aware client during the
SQLite-to-cache migration.

Google documents [Memorystore for Redis tiers and pricing][pricing], the
[supported versions and creation flags][create], and direct Cloud Run
[connectivity to Memorystore][cloud-run-redis].

## Network and transport

Both environments require all of the following:

- a reviewed private VPC and subnet selected through deployment configuration;
- a non-overlapping private-service allocation maintained in the operator
  infrastructure inventory;
- Redis authentication enabled;
- in-transit encryption with server authentication; and
- no public endpoint, localhost fallback, or container-launched Redis server.

Cloud Run revisions use [Direct VPC egress][direct-vpc]. The workflow resolves
the network, subnet, and egress policy from `CLOUD_RUN_VPC_NETWORK`,
`CLOUD_RUN_VPC_SUBNET`, and `CLOUD_RUN_VPC_EGRESS`; this document intentionally
does not record their environment-specific values. The runtime client uses
bounded pools, timeouts, and reconnect behavior to account for subnet address
consumption and connection resets.

Stage 8 enables the required managed-service APIs, creates the private
allocation and environment-specific instances, and validates TLS-authenticated
access from more than one Cloud Run instance before rollout.

## Authentication and secret boundaries

The authenticated URL and current server CA bundle are stored in separate
environment-specific secrets. Deployment resolves only their identifiers:

| Runtime | URL secret configuration | CA secret configuration |
| --- | --- | --- |
| Cloud Run | `CLOUD_RUN_RUNTIME_CACHE_URL_SECRET` | `CLOUD_RUN_RUNTIME_CACHE_CA_CERT_SECRET` |

Cloud Run resolves those secret identifiers and injects their values into
`RUNTIME_CACHE_URL` and `RUNTIME_CACHE_CA_CERT` on each revision.

Staging and production must not share an endpoint or credential. Endpoint,
port, expected TLS mode, and environment are explicit deployed settings;
application code must not infer them from v1 database configuration or fall
back to localhost.

The client validates the server certificate using in-memory `ssl_ca_data`.
CA rotation requires storing every currently valid CA in the environment's CA
secret before the provider rotates the serving certificate. Secret-bearing
URLs, authentication values, certificate material, concrete secret-resource
names, and workload identities must never be logged or added to migration
documentation or image layers.

## Namespace and loss semantics

Every key is namespaced by environment, service, cache family, and cache schema
version. Result keys additionally include every result-affecting input and
relevant package version. This is defense in depth around the physically
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
traffic unless its environment's endpoint, authentication secret, TLS
configuration, and VPC attachment are valid. New Stage 8 revisions use managed
Redis only; they never start or select an embedded Redis process.

The immediately preceding application revision retains its own prior runtime
configuration. Rolling back means moving traffic to that known-good revision.
It does not copy, restore, or downgrade cache contents. The managed cache may be
retained or flushed because cache loss is handled as a miss, and the dormant v2
Postgres schema remains in place unless an operator separately invokes a
reviewed migration downgrade.

If a rollout requires incompatible cache serialization, the new revision uses
a new cache-schema namespace. During a traffic split, old and new revisions may
therefore coexist without either revision reading the other's incompatible
values.

[cloud-run-redis]: https://cloud.google.com/memorystore/docs/redis/connect-redis-instance-cloud-run
[create]: https://cloud.google.com/memorystore/docs/redis/create-manage-instances
[direct-vpc]: https://cloud.google.com/run/docs/configuring/vpc-direct-vpc
[pricing]: https://cloud.google.com/memorystore/docs/redis/pricing
