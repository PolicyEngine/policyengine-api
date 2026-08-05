"""Country-ID validation shared by Flask and native FastAPI routes."""

from __future__ import annotations

from typing import Literal, TypedDict

from policyengine_api.constants import COUNTRIES


class CountryErrorPayload(TypedDict):
    status: Literal["error"]
    message: str


class InvalidCountryError(ValueError):
    """Raised when a public route receives an unsupported country ID."""

    def __init__(
        self,
        country_id: str,
        available_country_ids: tuple[str, ...] = COUNTRIES,
    ) -> None:
        self.country_id = country_id
        self.available_country_ids = available_country_ids
        super().__init__(
            f"Country {country_id} not found. Available countries are: "
            f"{', '.join(available_country_ids)}"
        )

    def to_payload(self) -> CountryErrorPayload:
        return {"status": "error", "message": str(self)}


def ensure_supported_country(country_id: str) -> str:
    """Return a supported country ID or raise the shared validation error."""
    if country_id not in COUNTRIES:
        raise InvalidCountryError(country_id)
    return country_id
