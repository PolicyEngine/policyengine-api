"""Proof fixture: version validation beside the catalog query. The rule rejects it.

This is the shape of the former mixed catalog selection module: importing it
for ``validate_policyengine_version`` also loads SQLAlchemy and SQLModel.
"""

from sqlmodel import Session, select

from policyengine_api.data.v2.models import TaxBenefitModelVersion


def validate_policyengine_version(value: str) -> str:
    """Return a non-empty version string."""
    if not value:
        msg = "policyengine_version must be non-empty"
        raise ValueError(msg)
    return value


def select_catalog(session: Session, version: str) -> TaxBenefitModelVersion | None:
    """Return the catalog version row for ``version``."""
    statement = select(TaxBenefitModelVersion).where(
        TaxBenefitModelVersion.version == validate_policyengine_version(version)
    )
    return session.exec(statement).first()
