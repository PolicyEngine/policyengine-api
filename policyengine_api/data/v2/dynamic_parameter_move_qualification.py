"""Read-only check before revision 7f7335f0eb31 moves dynamic parameters.

The revision moves every stored model assumption (``dynamic_parameters``'
prefixes) out of ``parameters``. Deleting one would delete every
``parameter_values`` row that names it, so a policy value naming one would
silently change its policy: the revision refuses to run while any exists.
This step counts the same values, in one ``READ ONLY`` transaction, while the
revision is pending, and stops the seed workflow before the schema upgrade
when there are any, so a deploy fails with the count before Alembic starts.
Operator step C1 · 49 splits such policies into a policy and a dynamic.

A parameter is a model assumption of its country, the country of its
catalog version's model ``policyengine-<country>``, as the revision decides.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, or_, select
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Parameter,
    ParameterValue,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.data.v2.pending_revisions import v2_revision_is_pending
from policyengine_api.data.v2.settings import (
    V2ConfigurationError,
    V2DatabaseSettings,
    load_v2_migration_database_settings,
)
from policyengine_api.dynamic_parameters import DYNAMIC_PARAMETER_PREFIXES

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from contextlib import AbstractContextManager

    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

DYNAMIC_PARAMETER_TABLES_REVISION = "7f7335f0eb31"


@dataclass(frozen=True)
class DynamicParameterMoveQualification:
    """Non-secret evidence that no policy value names a dynamic parameter.

    ``required`` is False when the revision was already applied, and nothing
    was counted.
    """

    environment: str
    project_ref: str
    policy_values_naming_dynamic_parameters: int
    required: bool = True

    def as_dict(self) -> dict[str, object]:
        """Return the evidence as the JSON object the command prints."""
        return {
            "outcome": "ok",
            "qualification": "performed" if self.required else "not-required",
            "environment": self.environment,
            "project_ref": self.project_ref,
            "counts": {
                "policy_values_naming_dynamic_parameters": (
                    self.policy_values_naming_dynamic_parameters
                )
            },
        }


class PolicyValuesNameDynamicParametersError(RuntimeError):
    """Raised while policy values name parameters the revision would move."""

    def __init__(self, count: int) -> None:
        """Keep the count and say in the message how to proceed."""
        self.count = count
        values = (
            "policy value names a dynamic parameter"
            if count == 1
            else ("policy values name dynamic parameters")
        )
        super().__init__(
            f"{count} {values} (gov.simulation., US simulation. or UK "
            "gov.dynamic.) in the configured Supabase target; the move of "
            "dynamic parameters into their own tables (revision "
            f"{DYNAMIC_PARAMETER_TABLES_REVISION}) would delete them with their "
            "parameters, so it stopped before the schema upgrade without "
            "modifying data. Split those policies into a policy and a dynamic "
            "first (operator step C1 · 49), then deploy again"
        )


def _names_a_dynamic_parameter() -> ColumnElement[bool]:
    """Select whether a parameter is a model assumption of its model's country."""
    return or_(
        *(
            and_(
                col(TaxBenefitModel.name) == f"policyengine-{country_id}",
                or_(
                    *(
                        func.starts_with(col(Parameter.name), prefix)
                        for prefix in prefixes
                    )
                ),
            )
            for country_id, prefixes in DYNAMIC_PARAMETER_PREFIXES.items()
        )
    )


def count_policy_values_naming_dynamic_parameters(session: Session) -> int:
    """Count the policy values whose parameter the revision would move."""
    count = session.scalar(
        select(func.count())
        .select_from(ParameterValue)
        .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
        .join(
            TaxBenefitModelVersion,
            col(TaxBenefitModelVersion.id)
            == col(Parameter.tax_benefit_model_version_id),
        )
        .join(
            TaxBenefitModel,
            col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
        )
        .where(
            col(ParameterValue.policy_id).is_not(None),
            _names_a_dynamic_parameter(),
        )
    )
    return int(count or 0)


def dynamic_parameter_move_is_pending(session: Session) -> bool:
    """Return whether revision 7f7335f0eb31 is in the upgrade path."""
    return v2_revision_is_pending(session, DYNAMIC_PARAMETER_TABLES_REVISION)


def open_qualification_sessions(
    settings: V2DatabaseSettings,
) -> AbstractContextManager[sessionmaker[Session]]:
    """Open Session factories whose every transaction is READ ONLY, with no pool."""
    from policyengine_api.data.v2.database import unpooled_v2_read_only_sessions

    return unpooled_v2_read_only_sessions(settings.connection.url)


def qualify_dynamic_parameter_move_if_pending(
    environ: Mapping[str, str] | None = None,
    *,
    session_factories: Callable[
        [V2DatabaseSettings], AbstractContextManager[sessionmaker[Session]]
    ] = open_qualification_sessions,
    pending_checker: Callable[[Session], bool] = dynamic_parameter_move_is_pending,
) -> DynamicParameterMoveQualification:
    """Count the policy values naming dynamic parameters while the move is pending.

    The revision check and the count run in one READ ONLY transaction, rolled
    back when the session closes. Raise PolicyValuesNameDynamicParametersError
    when there are any.
    """
    settings = load_v2_migration_database_settings(environ)
    with session_factories(settings) as sessions, sessions() as session:
        if not pending_checker(session):
            return DynamicParameterMoveQualification(
                environment=settings.target.environment,
                project_ref=settings.target.project_ref,
                policy_values_naming_dynamic_parameters=0,
                required=False,
            )
        count = count_policy_values_naming_dynamic_parameters(session)
    if count:
        raise PolicyValuesNameDynamicParametersError(count)
    return DynamicParameterMoveQualification(
        environment=settings.target.environment,
        project_ref=settings.target.project_ref,
        policy_values_naming_dynamic_parameters=0,
    )


def _error_payload(error: Exception) -> dict[str, object]:
    safe_errors = (V2ConfigurationError, PolicyValuesNameDynamicParametersError)
    message = (
        str(error)
        if isinstance(error, safe_errors)
        else "v2 dynamic parameter move qualification failed unexpectedly"
    )
    return {
        "outcome": "error",
        "error": {"type": type(error).__name__, "message": message},
    }


def main() -> int:
    """Run the check and return a shell-compatible status."""
    try:
        evidence = qualify_dynamic_parameter_move_if_pending()
    except Exception as error:  # noqa: BLE001  # command must emit safe evidence
        sys.stderr.write(json.dumps(_error_payload(error), sort_keys=True) + "\n")
        return 1
    sys.stdout.write(json.dumps(evidence.as_dict(), sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
