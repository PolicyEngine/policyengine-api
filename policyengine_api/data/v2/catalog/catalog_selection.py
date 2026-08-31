"""PolicyEngine.py catalog version selection for v2 resource reads."""

from __future__ import annotations

from dataclasses import dataclass

from packaging.version import InvalidVersion, Version
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from policyengine_api.data.v2.models import (
    TaxBenefitModel,
    TaxBenefitModelVersion,
)


SUPPORTED_PREVIEW_COUNTRIES = frozenset({"us", "uk"})


class MetadataCatalogUnavailableError(RuntimeError):
    """Raised when an initialized catalog cannot be read."""


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
        raise InvalidPolicyEngineVersionError(
            "policyengine_version must be a non-empty canonical version"
        )
    if len(value) > 128:
        raise InvalidPolicyEngineVersionError(
            "policyengine_version must be at most 128 characters"
        )
    try:
        parsed = Version(value)
    except InvalidVersion as error:
        raise InvalidPolicyEngineVersionError(
            "policyengine_version must be a canonical PEP 440 version"
        ) from error
    if str(parsed) != value or parsed == Version("0.0.0"):
        raise InvalidPolicyEngineVersionError(
            "policyengine_version must be a canonical non-placeholder version"
        )
    return value


def select_catalog(
    session: Session,
    *,
    country_id: str,
    running_policyengine_version: str,
    policyengine_version: str | None = None,
) -> SelectedCatalog:
    """Select one country catalog using the requested or running package version."""

    if country_id not in SUPPORTED_PREVIEW_COUNTRIES:
        raise UnsupportedPreviewCountryError(country_id)
    explicit_version = policyengine_version is not None
    selected_version = (
        validate_policyengine_version(policyengine_version)
        if explicit_version
        else running_policyengine_version
    )
    try:
        row = session.exec(
            select(TaxBenefitModel, TaxBenefitModelVersion)
            .join(
                TaxBenefitModelVersion,
                TaxBenefitModelVersion.model_id == TaxBenefitModel.id,
            )
            .where(
                TaxBenefitModel.name == f"policyengine-{country_id}",
                TaxBenefitModelVersion.version == selected_version,
            )
        ).one_or_none()
    except SQLAlchemyError as error:
        raise MetadataCatalogUnavailableError(
            "the v2 metadata catalog cannot be queried"
        ) from error

    if row is None:
        if explicit_version:
            raise MetadataCatalogVersionNotFoundError(
                f"PolicyEngine.py {selected_version} is not published for {country_id}"
            )
        raise MetadataCatalogUnavailableError(
            f"the running PolicyEngine.py {selected_version} catalog "
            f"is absent for {country_id}"
        )
    model, model_version = row
    return SelectedCatalog(
        country_id=country_id,
        policyengine_version=selected_version,
        model=model,
        model_version=model_version,
    )
