# API v2 Code Organization

API v2 resource code is divided by both resource and responsibility. Public
HTTP behavior must not be implemented in database repositories, and database
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
  read_repository.py
  write_repository.py
  catalog_repository.py
  legacy_mapping_repository.py
  canonicalization.py
user_policies/
  read_repository.py
  write_repository.py
  legacy_mapping_repository.py
metadata/
  read_models.py
  read_repository.py
  *_read_repository.py
```

Read repositories execute selections and return framework-neutral read models.
Write repositories mutate SQLModel rows using a caller-provided session.
Legacy mapping repositories contain durable identity-mapping SQL and conflict
handling. The shared `data/v2/catalog/` package remains responsible for catalog
initialization, publication, and catalog selection used by multiple resources.

The ordinary request direction is:

```text
route -> service -> repository -> SQLModel tables
```

HTTP response models may consume framework-neutral repository read models.
Repository write functions may consume immutable application command models,
but they must not import route modules or construct HTTP responses.
