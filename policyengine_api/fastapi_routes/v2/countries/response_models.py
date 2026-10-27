"""Strict HTTP response models for the native v2 countries list."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from policyengine_api.fastapi_routes.v2.errors import V2ErrorResponse

if TYPE_CHECKING:
    from policyengine_api.services.v2.countries.types import CountryRead


class StrictCountryAPIModel(BaseModel):
    """Strict response base with dataclass conversion support."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CountryItem(StrictCountryAPIModel):
    """One served country and the calculations it supports.

    ``id`` is the value other v2 resources take as ``country_id``.
    ``household_enabled`` means household calculations and saved households
    are available; ``society_wide_enabled`` means society-wide reports are,
    and is only set for a country that is also household enabled.
    """

    id: str
    household_enabled: bool
    society_wide_enabled: bool

    @classmethod
    def from_read(cls, country: CountryRead) -> CountryItem:
        """Build the response item from the service read record."""
        return cls.model_validate(country)


class CountryListResult(StrictCountryAPIModel):
    """Every served country, ordered by ``id``."""

    items: list[CountryItem]


class CountryListResponse(StrictCountryAPIModel):
    """Success envelope: ``status`` "ok", a null ``message`` and the countries."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: CountryListResult


COUNTRY_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    405: {
        "model": V2ErrorResponse,
        "description": "The countries list supports GET only.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The request has query parameters; the list takes none.",
    },
    500: {
        "model": V2ErrorResponse,
        "description": "The countries query failed internally.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": "The v2 database is not configured or cannot be reached.",
    },
}
