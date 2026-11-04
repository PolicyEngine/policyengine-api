"""The database read that selects one v2 catalog by PolicyEngine.py version.

Version validation, the error types and ``SelectedCatalog`` are in
``catalog_selection_validation``, which imports no database code.
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    SUPPORTED_V2_COUNTRY_IDS,
    MetadataCatalogNotPublishedError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    SelectedCatalog,
    UnsupportedPreviewCountryError,
    validate_policyengine_version,
)
from policyengine_api.data.v2.models import (
    TaxBenefitModel,
    TaxBenefitModelVersion,
)


def select_catalog(
    session: Session,
    *,
    country_id: str,
    running_policyengine_version: str,
    policyengine_version: str | None = None,
) -> SelectedCatalog:
    """Select one country catalog using the requested or running package version."""
    if country_id not in SUPPORTED_V2_COUNTRY_IDS:
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
        msg = "the v2 metadata catalog cannot be queried"
        raise MetadataCatalogUnavailableError(msg) from error

    if row is None:
        if explicit_version:
            msg = (
                f"PolicyEngine.py {selected_version} is not published for {country_id}"
            )
            raise MetadataCatalogVersionNotFoundError(msg)
        msg = (
            f"the running PolicyEngine.py {selected_version} catalog "
            f"is absent for {country_id}"
        )
        raise MetadataCatalogNotPublishedError(msg)
    model, model_version = row
    return SelectedCatalog(
        country_id=country_id,
        policyengine_version=selected_version,
        model=model,
        model_version=model_version,
    )
