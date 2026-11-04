"""Version validation, error types and the result type for v2 catalog selection.

This module imports no SQLAlchemy, SQLModel or database module, so v2
validators, transformations, types and routes can use it. The one database
read, ``select_catalog``, is in ``catalog_selection_reads``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version

from policyengine_api.supported_countries import SUPPORTED_COUNTRY_IDS

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import (
        TaxBenefitModel,
        TaxBenefitModelVersion,
    )

SUPPORTED_V2_COUNTRY_IDS = frozenset(SUPPORTED_COUNTRY_IDS)
MAXIMUM_POLICYENGINE_VERSION_LENGTH = 128


class MetadataCatalogUnavailableError(RuntimeError):
    """Raised when an initialized catalog cannot be read."""


class MetadataCatalogNotPublishedError(MetadataCatalogUnavailableError):
    """Raised when the running PolicyEngine.py version has no catalog for a country.

    The catalog was queried and holds no such version, as opposed to a query
    that failed.
    """


class UnsupportedPreviewCountryError(ValueError):
    """Raised when a country has no Stage 9 resource catalog."""


class InvalidPolicyEngineVersionError(ValueError):
    """Raised when an explicit version is not a canonical package version."""


class MetadataCatalogVersionNotFoundError(LookupError):
    """Raised when an explicitly selected catalog version is absent."""


@dataclass(frozen=True)
class SelectedCatalog:
    """One country catalog selected by its canonical PolicyEngine.py version."""

    country_id: str
    policyengine_version: str
    model: TaxBenefitModel
    model_version: TaxBenefitModelVersion


def validate_policyengine_version(value: str) -> str:
    """Return one bounded canonical PEP 440 version string."""
    if not isinstance(value, str) or not value or value != value.strip():
        msg = "policyengine_version must be a non-empty canonical version"
        raise InvalidPolicyEngineVersionError(msg)
    if len(value) > MAXIMUM_POLICYENGINE_VERSION_LENGTH:
        msg = (
            "policyengine_version must be at most "
            f"{MAXIMUM_POLICYENGINE_VERSION_LENGTH} characters"
        )
        raise InvalidPolicyEngineVersionError(msg)
    try:
        parsed = Version(value)
    except InvalidVersion as error:
        msg = "policyengine_version must be a canonical PEP 440 version"
        raise InvalidPolicyEngineVersionError(msg) from error
    if str(parsed) != value or parsed == Version("0.0.0"):
        msg = "policyengine_version must be a canonical non-placeholder version"
        raise InvalidPolicyEngineVersionError(msg)
    return value
