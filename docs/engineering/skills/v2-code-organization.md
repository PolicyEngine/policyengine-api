# API v2 Code Organization

Organize API v2 code first by resource and then by one explicit technical
responsibility. Route modules must not open database sessions or construct SQL
(rule `api.v2.routes-no-sessions-or-sql`). Service modules must sequence work
but must not construct or execute SQL (rule `api.v2.services-no-sql`).


## File layers

Every `.py` file under `policyengine_api/services/v2` and
`policyengine_api/fastapi_routes/v2` has a layer, which the `v2-layers` quality
guard (`scripts/rules/v2_layers.py`) takes from the file's name alone:

- under `services/v2/<resource>/`: `services.py` (service), `validators.py`,
  `transformations.py`, `types.py`, `process_state.py` (process-wide state),
  `database_session.py` (directly in the resource package) and
  `database_connectors/<creates|reads|updates|deletes>[_name].py`;
- under `fastapi_routes/v2/`: `routes.py` and `<name>_routes.py` (routes),
  `<name>_models.py` (request, response and document schemas) and
  `<name>_support.py` (HTTP code the route modules share);
- `__init__.py` anywhere.

A file with another name fails the guard (rule
`api.v2.files-assigned-to-layers`): rename it. A file that can't be renamed
needs a `[[rule.exception]]` for that rule in `rules/registry.toml`, with its
`path`, a `reason` and an `expires` date, by which the file should be renamed.
Write the path as `git ls-files` lists it, for a file git tracks. An exception
covers the whole file, so it sets no `match`, `category` or `removal`. A module
in a `database_connectors` package can't be excepted: that package holds only
connector modules, each named after its operation and placed directly in it
(rule `api.v2.crud-checks-cover-every-resource` also fails a module directly in
`services/v2/<resource>/database_connectors` whose name doesn't start with an
operation). Move a module that isn't a connector out of the package. An
exception chooses no layer: the file gets the route checks under
`fastapi_routes/v2`, and the validator, transformation and types checks
(rule `api.v2.pure-modules-no-session-calls`) under `services/v2`. The guard
fails on an exception for a file that no longer exists or whose name already
gives it a layer.

The guard counts a method call as a session call when its receiver is named
`session` or `<something>_session`, but not a request's `.session` or an HTTP
or client session (`http_session`, `requests_session`). Route modules and the
pure layers may call no method on a session at all. In routes, services and
the pure layers a call into SQLAlchemy or SQLModel counts, except to its
exception classes and, in services, to a session factory; a builder called on
a model's `__table__` counts too. A session factory is any call into
`policyengine_api.data.orm` or `policyengine_api.data.v2.database`,
SQLAlchemy's `Session`, `sessionmaker` or `create_engine`, or an injected
`*session_factory` or its `begin()`; only services and `database_session`
modules may use one. The guard doesn't
recognise a session bound to another name, an alias of a model's table, or a
name re-exported through another module. A ratcheted rule's baseline lists one
line per tolerated occurrence.

## HTTP adapters

Resource-specific FastAPI code lives under `policyengine_api/fastapi_routes/v2/`:

```text
errors_support.py
user_auth_support.py
user_resources_support.py
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
  route_support.py
  query_support.py
  response_cache_support.py
  search_file_support.py
  *_routes.py
```

`route_support.py` runs the metadata reads for the route modules, maps their
failures to HTTP, and holds the route class that gives metadata responses
their caching headers. `query_support.py` defines the typed FastAPI
dependencies for the shared query models once, for every metadata route
module to import. `response_cache_support.py` keeps serialized whole-version
responses (bodies and ETags) for the process; it is HTTP-level, so it lives
with the routes. `search_file_support.py` serves a stored parameter search
file with its content encoding.

`errors_support.py` defines the strict error response and serialization
function shared by every API v2 resource. `user_auth_support.py` turns
request credentials into an account principal, and
`user_resources_support.py` holds the HTTP conventions the user-owned
resource routes share. Application-wide exception handling distinguishes
API v2 from non-v2 requests but must not select error behavior by matching
individual resource paths.

Request models describe HTTP bodies. Response models describe public response
response structures and OpenAPI output. Route functions handle HTTP-only conditions,
invoke one service method, and convert typed failures to HTTP responses. No module
under `fastapi_routes/v2` imports SQLAlchemy, SQLModel, a connector, a
`database_session` module, the v1 ORM module `policyengine_api.data.orm` or
`policyengine_api.data.v2.database`, or calls a SQLAlchemy or SQLModel
function, a session method or a session factory (rule
`api.v2.routes-no-sessions-or-sql`; today's `sqlalchemy.exc` imports are in its
baseline).

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

A resource may also add a `process_state.py` module for process-wide state its
service reuses across requests, such as the metadata package's (each catalog
version a request has selected; after publication its row changes only in
its time-period options, its `catalog_last_published_at`, which no read uses,
and its `catalog_values_pruned_at`, which the service checks again before or
after the reads of the rows pruning deletes). Such a module holds plain data, constructs no
SQL and owns no session; the composition code creates one instance per process
and injects it into the service.

A service may also hand one group of its work to a class in a subpackage's
`services.py`, whose files take the same layer names: the metadata service
builds `MetadataCatalogSelection` from `metadata/catalog_selection/services.py`,
which selects the catalog version each read uses, with the process's kept
selections and the check for a pruned version.

Only add CRUD connector modules for operations the resource supports. Append a
specific descriptor when one operation file would become too broad, such as
`reads_variables.py` or `reads_parameter_tree.py`.

Policies currently have `creates.py` and `reads.py` because policies are
immutable. Metadata currently has only read connector modules because metadata
routes are read-only. User-policy associations have `creates.py`, `reads.py`,
`updates.py`, and `deletes.py` because they support all four operations.

### `services.py`

Define the overarching functions and classes called by route functions or
other application services. A service determines operation order, calls pure
validation and transformation functions, and passes a database session to one
or more connector functions. A service may expose an entrypoint that accepts an
existing session when several resources must change atomically in one caller-
owned transaction.

Do not construct SQL expressions, call `Session.exec` or another data-access
session method, or define HTTP response models in this module (rule
`api.v2.services-no-sql`, which also forbids importing FastAPI or Starlette).

### `validators.py`

Define functions that inspect already-available values and either return a
validated value or raise a typed exception. Validators must not load records,
open sessions, execute SQL, mutate database rows, or construct HTTP responses.
Validators, transformations, types, process-state modules and package
`__init__` files import nothing from SQLAlchemy or SQLModel but the `Session`
type, import no connector or session module, and call no session method,
SQLAlchemy or SQLModel function or session factory (rule
`api.v2.pure-modules-no-session-calls`).

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
but multi-record or catalog validation belongs in `validators.py`. Types and
transformations never import a validators module, directly or through other
modules; validators import types (rule
`api.v2.types-transformations-no-validators`, with today's exceptions in its
baseline).

### `database_session.py`

Define the resource's database-session lifetime container. It may open and
close sessions, begin transactions, commit, or roll back. It must not construct
SQL, choose records, validate business rules, transform records into response
types, or determine multi-step operation order. It calls no data-access
session method (`add`, `get`, `merge`, `exec`, `execute` and so on) and
imports no connector (rule `api.v2.session-modules-no-data-access`).

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
commit, roll back, or close it (rule `api.v2.connectors-never-commit`). They do not call route functions, perform
request-level or business validation, or convert rows into public response
types. Connector modules do not call one another to sequence a workflow; the
service makes that ordering explicit. They never import one another (rule
`api.v2.connectors-no-cross-calls`, with today's exceptions in its baseline).

The module name also decides which table privileges the connector needs
(rule `api.v2.runtime-privileges-declared`): `reads` modules need SELECT;
`creates`, `updates` and `deletes` modules need INSERT, UPDATE or DELETE, plus
SELECT; and a function that locks rows with `with_for_update` needs UPDATE on
the tables it locks. A connector that starts using a table, or a new kind of
operation on one, needs that privilege declared in
`policyengine_api/data/v2/privileges.py` in the same pull request; see
[Table privileges](alembic-migrations.md#table-privileges).

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

Import Linter checks these directions in CI with the contracts in
`[tool.importlinter]` in `pyproject.toml`. Imports made only under
`TYPE_CHECKING` count:

- v2 routes may import v2 services and v2 data modules, and v2 services may
  import v2 data modules, never the reverse, directly or through other modules
  (rule `api.v2.import-layers`);
- v2 route modules never import a connector, a `database_session` module or
  `policyengine_api.data.v2.database` themselves (rule
  `api.v2.routes-import-no-database-access`). They reach them through
  `fastapi_routes/dependencies.py` and the services they call, so this
  contract checks direct imports only;
- validators, transformations and types never reach SQLAlchemy, SQLModel, a
  connector, a `database_session` module or the v2 database module, directly
  or through other modules, except through the table models (rule
  `api.v2.pure-modules-no-database`).

The table models' own imports of SQLAlchemy and SQLModel are allowed, one
model module at a time, so a new module in `policyengine_api/data/v2/models/`
needs its two imports added to the rule. Import Linter reads import
statements. It does not see a name that a module re-exports from another, and
a tolerated exception covers every import between its two modules and every
chain through them: today `identity.types -> sqlmodel` also covers
`identity.transformations`, `user_accounts.types`,
`user_accounts.transformations` and `user_accounts.validators`, which reach
SQLModel only through it.

Catalog version validation, its error types and `SelectedCatalog` live in
`policyengine_api/data/v2/catalog/catalog_selection_validation.py`, which
loads no database code, so validators, transformations, types and routes may
import it (rule `api.catalog.selection-validation-no-database`). The catalog
query itself, `select_catalog`, is in `catalog_selection_reads.py`; the
policies and metadata read connectors call it.

Database connectors may consume service-layer input types when inserting or
updating rows. They must not import route modules. Validators and
transformations may consume types and already-loaded database model instances,
but must not depend on SQLAlchemy or SQLModel query/session APIs.
