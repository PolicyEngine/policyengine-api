# API v2 Code Organization

API v2 resource code is divided by both resource and responsibility. Public
HTTP behavior must not be implemented in database-access modules, and database
sessions and transactions must not be opened by route modules.

## HTTP adapters

Resource-specific FastAPI code lives under `policyengine_api/fastapi_routes/v2/`:

```text
policies/
  request_models.py
  response_models.py
  routes.py
user_policies/
  request_models.py
  response_models.py
  routes.py
metadata/
  response_models.py
  common.py
  *_routes.py
```

Request models describe HTTP request bodies. Response models describe the
public response envelope and OpenAPI output. Route modules validate HTTP-only
conditions, invoke application services, and convert typed failures to HTTP
responses.

## Application services

Resource-specific application code lives under `policyengine_api/services/v2/`:

```text
policies/
  commands.py
  catalog_validation.py
  canonicalization.py
  creation.py
  legacy_translation.py
  legacy_service.py
  service.py
user_policies/
  commands.py
  legacy_translation.py
  legacy_service.py
  service.py
metadata/
  service.py
```

Command models are independent of FastAPI and Flask. Native services own
request-level database sessions and transaction boundaries. Legacy translation
converts committed v1 snapshots into v2 commands. Legacy services coordinate
all work that must occur inside one Supabase transaction. Catalog validation
operates only on already-loaded records and must not execute SQL. Policy
canonicalization is deterministic application logic and must not access a
database.

## Database access

SQL reads and writes live under `policyengine_api/data/v2/`:

```text
policies/
  creates.py
  reads.py
user_policies/
  creates.py
  reads.py
  updates.py
  deletes.py
metadata/
  read_models.py
  read_support.py
  *_reads.py
```

Database-access modules are organized by SQL operation rather than by HTTP
method or table. Read modules contain every `SELECT` and `Session.get`
operation used by the resource, including reads performed while processing a
create, update, or delete request. Create modules contain inserts and ORM row
creation. Update modules modify existing rows. Delete modules remove rows. A
request may use several CRUD modules while the application service sequences
those calls and owns the transaction.

Do not create an empty CRUD module for an operation the resource does not
support. Immutable policies therefore have only `creates.py` and `reads.py`.
Mutable user-policy associations have all four modules. Read-only metadata
uses resource-specific `*_reads.py` modules and shared `read_support.py`.

Legacy mapping SQL follows the same division: mapping selection belongs in
`reads.py`, mapping insertion in `creates.py`, mapping mutation in `updates.py`,
and mapping removal in `deletes.py`. Mapping validation and retry sequencing
belong in application services, not database-access modules. The shared
`data/v2/catalog/` package remains responsible for catalog initialization,
publication, and catalog selection used by multiple resources.

Name a database-access module for the CRUD operation it implements.
Do not use `repository` as a generic synonym for SQL access. Reserve that term
for a deliberate Repository-pattern abstraction with a stable interface that
hides interchangeable persistence implementations. Direct SQL CRUD modules in
API v2 do not currently provide that abstraction.

The ordinary request direction is:

```text
route -> service -> one or more CRUD modules -> SQLModel tables
```

HTTP response models may consume framework-neutral database read models.
CRUD functions may consume immutable application command models, but
database-access modules must not import route modules, perform request-level
validation, control the transaction, or construct HTTP responses. CRUD modules
must not call one another; the application service makes their ordering and
shared transaction explicit.
