"""Controlled imports and metadata export for the reviewed v2 schema."""

from sqlmodel import SQLModel

from policyengine_api.data.v2.metadata_validation import (
    validate_v2_metadata_table_names,
)

# Apply deterministic names before any v2 table is declared. This is a local
# SQLAlchemy metadata facility that SQLModel does not wrap directly.
SQLModel.metadata.naming_convention = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Import in dependency order so every reviewed table registers exactly once.
from policyengine_api.data.v2.models.associations import (  # noqa: E402
    UserHouseholdAssociation,
    UserPolicy,
    UserReportAssociation,
    UserSimulationAssociation,
)
from policyengine_api.data.v2.models.comparison_runs import (  # noqa: E402
    Stage12AggregationStatus,
    Stage12ComparisonReport,
    Stage12ComparisonSimulation,
    Stage12ResultComparisonStatus,
    Stage12RunStatus,
    Stage12SimulationRole,
)
from policyengine_api.data.v2.models.household_mappings import (  # noqa: E402
    LegacyHouseholdMapping,
)
from policyengine_api.data.v2.models.households import (  # noqa: E402
    Household,
)
from policyengine_api.data.v2.models.metadata import (  # noqa: E402
    Dataset,
    DatasetVersion,
    Parameter,
    ParameterNode,
    ParameterValue,
    Region,
    RegionType,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)
from policyengine_api.data.v2.models.policies import (  # noqa: E402
    Dynamic,
    Policy,
)
from policyengine_api.data.v2.models.policy_mappings import (  # noqa: E402
    LegacyPolicyMapping,
    LegacyUserMapping,
    LegacyUserPolicyMapping,
)
from policyengine_api.data.v2.models.users import (  # noqa: E402
    User,
    UserIdentity,
    UserType,
)

V2_METADATA = SQLModel.metadata
validate_v2_metadata_table_names(V2_METADATA.tables)

__all__ = [
    "V2_METADATA",
    "Dataset",
    "DatasetVersion",
    "Dynamic",
    "Household",
    "LegacyHouseholdMapping",
    "LegacyPolicyMapping",
    "LegacyUserMapping",
    "LegacyUserPolicyMapping",
    "Parameter",
    "ParameterNode",
    "ParameterValue",
    "Policy",
    "Region",
    "RegionType",
    "Stage12AggregationStatus",
    "Stage12ComparisonReport",
    "Stage12ComparisonSimulation",
    "Stage12ResultComparisonStatus",
    "Stage12RunStatus",
    "Stage12SimulationRole",
    "TaxBenefitModel",
    "TaxBenefitModelVersion",
    "User",
    "UserHouseholdAssociation",
    "UserIdentity",
    "UserPolicy",
    "UserReportAssociation",
    "UserSimulationAssociation",
    "UserType",
    "Variable",
]
