# API v2 Code Organization

Organize API v2 code first by resource and then by one explicit technical
responsibility. Route modules must not open database sessions or construct SQL.
Service modules must sequence work but must not construct or execute SQL.

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

Request models describe HTTP bodies. Response models describe public response
envelopes and OpenAPI output. Route functions handle HTTP-only conditions,
invoke one service method, and convert typed failures to HTTP responses.

## Resource service packages

New and moved API v2 resource code uses this layout:

```text
services/v2/<resource>/
  services.py
  validators.py
  transformations.py
  types.py
  database_session.py
  database_connectors/
    __init__.py
    creates.py
    reads.py
    updates.py
    deletes.py
```

Only add CRUD connector modules for operations the resource supports. Append a
specific descriptor when one operation file would become too broad, such as
`reads_variables.py` or `reads_parameter_tree.py`.

Policies currently have `creates.py` and `reads.py` because policies are
immutable. Metadata currently has only read connector modules because metadata
routes are read-only. User-policy associations support creation, reading,
updating, and deletion; migrate that existing package to this layout when its
modules are next moved or substantially changed.

### `services.py`

Define the overarching functions and classes called by route functions or
other application services. A service determines operation order, calls pure
validation and transformation functions, and passes a database session to one
or more connector functions. A service may expose an entrypoint that accepts an
existing session when several resources must change atomically in one caller-
owned transaction.

Do not construct SQL expressions, call `Session.exec`, or define HTTP response
models in this module.

### `validators.py`

Define functions that inspect already-available values and either return a
validated value or raise a typed exception. Validators must not load records,
open sessions, execute SQL, mutate database rows, or construct HTTP responses.

When validation depends on stored state, a database connector loads the
required rows and the service passes those rows to a validator. For example,
policy catalog membership is checked only after a read connector returns the
selected catalog and matching parameter identifiers.

### `transformations.py`

Define deterministic conversions between representations. Examples include
converting database rows to service result types, translating a detached v1
snapshot into v2 input using already-loaded catalog records, and producing a
canonical byte representation for content deduplication.

Transformation functions must not open sessions, execute SQL, mutate database
rows, own transaction behavior, or construct HTTP responses.

### `types.py`

Define framework-independent Pydantic models, dataclasses, enums, and type
aliases exchanged between routes, services, validators, transformations, and
database connectors. Names should describe the represented data, such as
`PolicyCreationInput`, not an architectural pattern such as “command.”

Types may enforce their own field-level invariants through Pydantic validation,
but multi-record or catalog validation belongs in `validators.py`.

### `database_session.py`

Define the resource's database-session lifetime container. It may open and
close sessions, begin transactions, commit, or roll back. It must not construct
SQL, choose records, validate business rules, transform records into response
types, or determine multi-step operation order.

Composition code should construct this container and inject it into the
service. A request-scoped read service may wrap one already-open session; a
write service may wrap a session factory and expose read and transaction
context managers.

### `database_connectors/`

Every function that constructs or executes SQL, calls `Session.get`, or mutates
ORM rows belongs in this package. Organize connector files by CRUD operation:

- `creates.py` inserts rows or adds new ORM objects.
- `reads.py` contains `SELECT` operations and `Session.get` calls.
- `updates.py` changes existing rows.
- `deletes.py` removes rows.

Connector functions receive a session from the service. They do not open,
commit, roll back, or close it. They do not call route functions, perform
request-level or business validation, or convert rows into public response
types. Connector modules do not call one another to sequence a workflow; the
service makes that ordering explicit.

Do not use `repository` as a generic synonym for SQL access. Reserve that term
for an intentional Repository-pattern abstraction with a stable interface that
hides interchangeable persistence implementations. API v2 currently uses
direct database connector functions.

## Dependency direction

The normal dependency direction is:

```text
route -> service -> database session + database connectors -> SQLModel tables
                   -> validators
                   -> transformations
                   -> types
```

Database connectors may consume service-layer input types when inserting or
updating rows. They must not import route modules. Validators and
transformations may consume types and already-loaded database model instances,
but must not depend on SQLAlchemy or SQLModel query/session APIs.
