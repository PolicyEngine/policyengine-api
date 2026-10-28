"""Pure representation transformations for v2 user-report operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from policyengine_api.services.v2.associations.types import RecordReferences
from policyengine_api.services.v2.user_reports.types import (
    SharedBaselineReformRead,
    SharedUserReportRead,
    UserReportCreateFields,
    UserReportCreationInput,
    UserReportPage,
    UserReportRead,
    UserReportUpdateInput,
    stored_provisions,
    stored_validation,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import UserPolicy, UserReportAssociation


def user_report_read(association: UserReportAssociation) -> UserReportRead:
    """Convert a stored association row to the service's read model."""
    return UserReportRead(
        id=association.id,
        country_id=association.country_id,
        user_id=association.user_id,
        report_id=association.report_id,
        legacy_report_id=association.legacy_report_id,
        name=association.name,
        description=association.description,
        user_policy_id=association.user_policy_id,
        baseline_user_policy_id=association.baseline_user_policy_id,
        source_note=association.source_note,
        provisions=association.provisions,
        validation=association.validation,
        budget_window_years=association.budget_window_years,
        last_run_at=association.last_run_at,
        created_at=association.created_at,
        updated_at=association.updated_at,
    )


def shared_user_report_read(
    association: UserReportAssociation,
    *,
    baseline_reform: UserPolicy | None,
) -> SharedUserReportRead:
    """Build the view of a saved report that anyone holding its link may read.

    The owner, the description and the saved-reform IDs are left out;
    ``baseline_reform`` is the saved reform the report was compared with, which
    the view names, or None.
    """
    return SharedUserReportRead(
        id=association.id,
        country_id=association.country_id,
        report_id=association.report_id,
        legacy_report_id=association.legacy_report_id,
        name=association.name,
        source_note=association.source_note,
        provisions=association.provisions,
        validation=association.validation,
        budget_window_years=association.budget_window_years,
        baseline_reform=(
            None
            if baseline_reform is None
            else SharedBaselineReformRead(name=baseline_reform.name)
        ),
        last_run_at=association.last_run_at,
        created_at=association.created_at,
        updated_at=association.updated_at,
    )


def user_report_page(
    rows: list[UserReportAssociation],
    *,
    offset: int,
    limit: int,
) -> UserReportPage:
    """Build a page from up to ``limit + 1`` rows.

    The extra row is not returned; it only sets ``has_more``.
    """
    return UserReportPage(
        items=tuple(user_report_read(row) for row in rows[:limit]),
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )


def owned_user_report_input(
    fields: UserReportCreateFields,
    *,
    user_id: UUID,
) -> UserReportCreationInput:
    """Add the resolved owner and serialize the provision and validation snapshots."""
    return UserReportCreationInput(
        **fields.model_dump(exclude={"provisions", "validation"}),
        provisions=stored_provisions(fields.provisions),
        validation=stored_validation(fields.validation),
        user_id=user_id,
    )


def user_report_update_values(
    association_input: UserReportUpdateInput,
) -> dict[str, Any]:
    """Return explicitly supplied fields with JSON documents normalized."""
    values = association_input.model_dump(
        exclude_unset=True,
        exclude={"provisions", "validation"},
    )
    if "provisions" in association_input.model_fields_set:
        values["provisions"] = stored_provisions(association_input.provisions)
    if "validation" in association_input.model_fields_set:
        values["validation"] = stored_validation(association_input.validation)
    return values


def stored_report_references(association: UserReportAssociation) -> RecordReferences:
    """Return the v2 report and v1 report output a stored saved report names."""
    return RecordReferences(
        v2_id=association.report_id, legacy_id=association.legacy_report_id
    )
