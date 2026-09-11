"""Canonical query-parameter definitions shared by HTTP frameworks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from types import UnionType
from typing import Annotated, Any, Literal, TypeVar, Union, get_args, get_origin
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from policyengine_api.data.v2.catalog.catalog_selection import (
    validate_policyengine_version,
)
from policyengine_api.spm import SPMSelection
from policyengine_api.utils.budget_window import (
    BUDGET_WINDOW_MAX_END_YEAR,
    BUDGET_WINDOW_MAX_YEARS,
)


DEFAULT_QUERY_LIMIT = 100
MAXIMUM_QUERY_LIMIT = 500
MAXIMUM_USER_ID_LENGTH = 255
SUPPORTED_COUNTRY_IDS = frozenset({"us", "uk"})


def normalize_country_id(value: Any) -> Any:
    """Lowercase a textual country ID before its supported-value check."""

    return value.lower() if isinstance(value, str) else value


def validate_legacy_user_id(value: str) -> str:
    """Reject an empty or whitespace-only legacy user identifier."""

    if not value.strip():
        raise ValueError(
            "legacy user_id must contain at least one non-whitespace character"
        )
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
DefaultYear = Annotated[
    int,
    Field(
        ge=1900,
        le=2200,
        description="Default year for values without explicit period keys",
    ),
]
UserId = Annotated[
    UUID,
    Field(description="V2 user UUID; does not prove caller control"),
]
LegacyUserId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAXIMUM_USER_ID_LENGTH,
        description="Exact opaque v1 user identifier",
    ),
    AfterValidator(validate_legacy_user_id),
]


class StrictQueryParameters(BaseModel):
    """Base for query contracts that reject every undeclared field.

    ``EconomyQuery`` and its subclasses are the one family that overrides this
    to ignore undeclared parameters; see its docstring for why.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"SPM field {name!r} must not be repeated")
        result[name] = value
    return result


def parse_spm_query_value(value: Any) -> Any:
    """Decode a single JSON object, preserving omissions and rejecting duplicates."""
    if isinstance(value, str):
        value = json.loads(value, object_pairs_hook=_unique_json_object)
    if not isinstance(value, (dict, SPMSelection)):
        raise ValueError("spm must be a JSON object")
    return value


def parse_integer_query_value(value: Any) -> Any:
    """Preserve integer-string parsing; decimal spellings such as 2.0 are invalid."""
    return int(value) if isinstance(value, str) else value


EconomyRegion = Annotated[str, Field(min_length=1, description="Sub-national region")]
EconomyYear = Annotated[
    str, Field(pattern=r"^[0-9]{4}$", description="Four-digit calendar year")
]
SPMQuerySelection = Annotated[SPMSelection, BeforeValidator(parse_spm_query_value)]


class EconomyQuery(StrictQueryParameters):
    """Common legacy economy query options; identifiers remain in the path.

    These legacy GET routes accepted any query string before the typed parser,
    and callers still append parameters the routes never read, such as the
    ``staging_probe`` correlation id the release gate's live suite sends. An
    undeclared parameter is therefore ignored rather than rejected: an omitted
    ``spm`` selection already dispatches the certified default measurement, so
    a misspelled one cannot select anything else. Declared parameters keep
    their validation, repeated scalars are still rejected, and the ``spm``
    object itself stays strict.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    region: EconomyRegion
    dataset: str = Field(default="default", description="Dataset selection")
    version: str | None = Field(
        default=None,
        description="Country model version; omission uses the installed version",
    )
    include_district_breakdowns: bool = Field(
        default=False,
        deprecated=True,
        description="Deprecated no-op; district results are returned automatically",
    )
    spm: SPMQuerySelection | None = Field(
        default=None, description="A single JSON-encoded SPM selection object"
    )

    def calculation_options(self) -> dict[str, Any]:
        """Return only public computation options, with omissions preserved."""
        return {} if self.spm is None else {"spm": self.spm.model_dump(mode="json")}


class AnnualEconomyQuery(EconomyQuery):
    """Complete query contract for the annual economy route."""

    time_period: EconomyYear
    target: Literal["general", "cliff"] = "general"


class BudgetWindowEconomyQuery(EconomyQuery):
    """Complete query contract for the budget-window economy route."""

    start_year: EconomyYear
    window_size: Annotated[int, BeforeValidator(parse_integer_query_value)] = Field(
        ge=1,
        le=BUDGET_WINDOW_MAX_YEARS,
        description="Number of years; start_year + window_size - 1 must not exceed 2099",
    )
    target: Literal["general"] = "general"

    @model_validator(mode="after")
    def validate_end_year(self) -> BudgetWindowEconomyQuery:
        if int(self.start_year) + self.window_size - 1 > BUDGET_WINDOW_MAX_END_YEAR:
            raise ValueError(
                f"budget-window end_year must be {BUDGET_WINDOW_MAX_END_YEAR} or earlier"
            )
        return self


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
    """Query contract for one v2 user's policy associations."""

    user_id: UserId
    policy_id: ResourceId | None = None


class HouseholdCreateQuery(CountryQuery):
    """Query contract for native immutable household creation."""


class HouseholdDetailQuery(CountryQuery):
    """Query contract for country-scoped household detail reads."""


class HouseholdCollectionQuery(CountryQuery, PaginationQuery):
    """Query contract for an exact-filtered household collection."""

    default_year: DefaultYear | None = None


class UserHouseholdCreateQuery(CountryQuery):
    """Query contract for native user-household association creation."""


class UserHouseholdDetailQuery(CountryQuery):
    """Query contract for country-scoped association detail reads."""


class UserHouseholdCollectionQuery(CountryQuery, PaginationQuery):
    """Query contract for one v2 user's household associations."""

    user_id: UserId
    household_id: ResourceId | None = None


class UserHouseholdUpdateQuery(CountryQuery):
    """Query contract for country-scoped association updates."""


class UserHouseholdDeleteQuery(CountryQuery):
    """Query contract for country-scoped association deletion."""


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
