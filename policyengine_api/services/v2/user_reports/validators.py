"""Database-independent validation for v2 user-report operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.validators import (
    AssociationLinkNotFoundError,
    AssociationNotFoundError,
    AssociationReferenceConflictError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import UserReportAssociation


class UserReportNotFoundError(AssociationNotFoundError):
    """Raised when an association is absent for the caller and country."""


class AssociationReportNotFoundError(LookupError):
    """A saved report names a detailed-save report the country does not have."""


class AssociationBudgetWindowConflictError(AssociationReferenceConflictError):
    """A saved report's budget_window_years disagrees with the report it names."""


# A saved report stores a window of one year as no window.
SMALLEST_SAVED_BUDGET_WINDOW = 2

# The foreign key from saved reports to reports (``RESTRICT``).
SAVED_REPORT_FOREIGN_KEY = "fk_user_report_associations_report_id_reports"


def report_not_found(
    *, report_id: UUID, country_id: str
) -> AssociationReportNotFoundError:
    """Return the error for a detailed-save report the country does not have."""
    return AssociationReportNotFoundError(
        f"Report {report_id} was not found in country {country_id!r}"
    )


def require_stored_report(*, stored: bool, report_id: UUID, country_id: str) -> None:
    """Raise AssociationReportNotFoundError unless the report is ``stored``."""
    if not stored:
        raise report_not_found(report_id=report_id, country_id=country_id)


def require_matching_budget_window(
    *,
    report_id: UUID,
    budget_window_size: int | None,
    budget_window_years: int | None,
) -> None:
    """Raise unless the saved report's window agrees with the report's own.

    ``budget_window_size`` is the report's window, and ``budget_window_years``
    the saved report's. A report with a window of two or more years needs the
    same number; any other report, whose window is one year or none, needs
    none, since a saved report stores a one-year window as none. Raise
    AssociationBudgetWindowConflictError when they disagree.
    """
    if (
        budget_window_size is not None
        and budget_window_size >= SMALLEST_SAVED_BUDGET_WINDOW
    ):
        if budget_window_years != budget_window_size:
            msg = (
                f"budget_window_years must be {budget_window_size}, the budget "
                f"window of report {report_id}"
            )
            raise AssociationBudgetWindowConflictError(msg)
        return
    if budget_window_years is not None:
        msg = (
            f"budget_window_years must be null: report {report_id} has no budget "
            "window of two or more years"
        )
        raise AssociationBudgetWindowConflictError(msg)


def require_user_report(
    association: UserReportAssociation | None,
    *,
    association_id: UUID,
) -> UserReportAssociation:
    """Return the association, or raise UserReportNotFoundError if it is None."""
    if association is None:
        msg = f"user-report association {association_id} was not found"
        raise UserReportNotFoundError(msg)
    return association


def require_owned_user_policy(*, owned: bool, user_policy_id: UUID) -> None:
    """Raise AssociationLinkNotFoundError unless a linked saved policy is ``owned``.

    ``owned`` says whether the report's owner has that saved policy in the
    report's country.
    """
    if not owned:
        msg = (
            f"user-policy association {user_policy_id} was not found for this "
            "user and country"
        )
        raise AssociationLinkNotFoundError(msg)
