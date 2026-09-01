"""Canonical query-parameter definitions shared by HTTP frameworks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import UnionType
from typing import Annotated, Any, Literal, TypeVar, Union, get_args, get_origin
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
)

from policyengine_api.data.v2.catalog.catalog_selection import (
    validate_policyengine_version,
)


DEFAULT_QUERY_LIMIT = 100
MAXIMUM_QUERY_LIMIT = 500
MAXIMUM_USER_ID_LENGTH = 255
SUPPORTED_COUNTRY_IDS = frozenset({"us", "uk"})


def normalize_country_id(value: Any) -> Any:
    """Lowercase a textual country ID before its supported-value check."""

    return value.lower() if isinstance(value, str) else value


def validate_user_id(value: str) -> str:
    """Reject an empty or whitespace-only caller-supplied identifier."""

    if not value.strip():
        raise ValueError("user_id must contain at least one non-whitespace character")
    return value


CountryId = Annotated[
    Literal["us", "uk"],
    BeforeValidator(normalize_country_id),
    Field(description="Supported PolicyEngine country ID"),
]
PolicyEngineVersion = Annotated[
    str,
    Field(max_length=128, description="Canonical non-placeholder PEP 440 version"),
    AfterValidator(validate_policyengine_version),
]
Offset = Annotated[int, Field(ge=0, description="Zero-based result offset")]
Limit = Annotated[
    int,
    Field(
        ge=1,
        le=MAXIMUM_QUERY_LIMIT,
        description="Maximum number of returned resources",
    ),
]
ResourceId = Annotated[UUID, Field(description="Exact resource UUID")]
UserId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAXIMUM_USER_ID_LENGTH,
        description="Unverified caller-supplied user identifier",
    ),
    AfterValidator(validate_user_id),
]


class StrictQueryParameters(BaseModel):
    """Base for query contracts that reject every undeclared field."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CountryQuery(StrictQueryParameters):
    """Required country selection shared by country-scoped routes."""

    country_id: CountryId


class CatalogQuery(CountryQuery):
    """Country plus an optional exact PolicyEngine.py catalog version."""

    policyengine_version: PolicyEngineVersion | None = None


class PaginationQuery(StrictQueryParameters):
    """Canonical bounded offset/limit pagination."""

    offset: Offset = 0
    limit: Limit = DEFAULT_QUERY_LIMIT


class PolicyCreateQuery(CatalogQuery):
    """Query contract for native immutable policy creation."""


class PolicyDetailQuery(CountryQuery):
    """Query contract for country-scoped policy detail reads."""


class PolicyCollectionQuery(CountryQuery, PaginationQuery):
    """Query contract for an exact-filtered policy collection."""

    tax_benefit_model_id: ResourceId | None = None


class UserPolicyCollectionQuery(CountryQuery, PaginationQuery):
    """Query contract for one caller-supplied user's policy associations."""

    user_id: UserId
    policy_id: ResourceId | None = None


QueryParametersT = TypeVar("QueryParametersT", bound=StrictQueryParameters)


class DuplicateScalarQueryParameterError(ValueError):
    """Raised when a scalar query field is supplied more than once."""

    def __init__(self, parameter_name: str) -> None:
        self.parameter_name = parameter_name
        super().__init__(
            f"scalar query parameter {parameter_name!r} must not be repeated"
        )


def _annotation_is_list(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin is list:
        return True
    if origin in (Union, UnionType):
        return any(_annotation_is_list(member) for member in get_args(annotation))
    return False


def query_field_multiplicity(
    model_type: type[StrictQueryParameters],
) -> Mapping[str, bool]:
    """Return public query names mapped to whether repeated values are valid."""

    return {
        (field.alias or field_name): _annotation_is_list(field.annotation)
        for field_name, field in model_type.model_fields.items()
    }


def validate_scalar_query_multiplicity(
    model_type: type[StrictQueryParameters],
    items: Iterable[tuple[str, str]],
) -> None:
    """Reject a repeated declared scalar while allowing declared list fields."""

    multiplicity = query_field_multiplicity(model_type)
    seen: set[str] = set()
    for name, _value in items:
        if name not in multiplicity or multiplicity[name]:
            continue
        if name in seen:
            raise DuplicateScalarQueryParameterError(name)
        seen.add(name)


def parse_query_items(
    model_type: type[QueryParametersT],
    items: Iterable[tuple[str, str]],
) -> QueryParametersT:
    """Validate ordered query pairs through one canonical Pydantic schema."""

    pairs = list(items)
    validate_scalar_query_multiplicity(model_type, pairs)
    multiplicity = query_field_multiplicity(model_type)
    values: dict[str, object] = {}
    for name, value in pairs:
        if multiplicity.get(name, False):
            values.setdefault(name, [])
            list_values = values[name]
            if isinstance(list_values, list):
                list_values.append(value)
            continue
        values[name] = value
    return model_type.model_validate(values)


def parse_multidict_query(
    model_type: type[QueryParametersT],
    query_input: object,
) -> QueryParametersT:
    """Adapt a Flask/Werkzeug-style MultiDict to the canonical parser."""

    items_method = getattr(query_input, "items", None)
    if not callable(items_method):
        raise TypeError("query input must provide an items method")
    try:
        items = items_method(multi=True)
    except TypeError as error:
        raise TypeError("query input must preserve repeated keys") from error
    return parse_query_items(model_type, items)
