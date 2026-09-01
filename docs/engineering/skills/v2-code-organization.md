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
all work that must occur inside one Supabase transaction.

## Database access

SQL reads and writes live under `policyengine_api/data/v2/`:

```text
policies/
  queries.py
  persistence.py
  catalog_resolution.py
  legacy_mappings.py
  canonicalization.py
user_policies/
  queries.py
  persistence.py
  legacy_mappings.py
metadata/
  read_models.py
  query_support.py
  *_queries.py
```

Query modules execute selections and return framework-neutral read models.
Persistence modules insert, update, or delete SQLModel rows using a
caller-provided session. Catalog-resolution modules select and validate the
exact catalog records needed by a resource. Legacy-mapping modules contain the
SQL and conflict handling for durable legacy-ID mappings. The shared
`data/v2/catalog/` package remains responsible for catalog initialization,
publication, and catalog selection used by multiple resources.

Name a database-access module for the operation or data concern it implements.
Do not use `repository` as a generic synonym for SQL access. Reserve that term
for a deliberate Repository-pattern abstraction with a stable interface that
hides interchangeable persistence implementations. Direct SQL query and
mutation modules in API v2 do not currently provide that abstraction.

The ordinary request direction is:

```text
route -> service -> query or persistence module -> SQLModel tables
```

HTTP response models may consume framework-neutral database read models.
Persistence functions may consume immutable application command models, but
database-access modules must not import route modules or construct HTTP
responses.
