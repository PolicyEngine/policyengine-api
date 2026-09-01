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
from policyengine_api.data.v2.models.users import User  # noqa: E402
from policyengine_api.data.v2.models.policies import (  # noqa: E402
    Dynamic,
    Policy,
)
from policyengine_api.data.v2.models.households import (  # noqa: E402
    Household,
    HouseholdJob,
    HouseholdJobStatus,
)
from policyengine_api.data.v2.models.simulations import (  # noqa: E402
    Simulation,
    SimulationStatus,
    SimulationType,
)
from policyengine_api.data.v2.models.associations import (  # noqa: E402
    UserHouseholdAssociation,
    UserPolicy,
    UserReportAssociation,
    UserSimulationAssociation,
)
from policyengine_api.data.v2.models.policy_mappings import (  # noqa: E402
    LegacyPolicyMapping,
    LegacyUserPolicyMapping,
)
from policyengine_api.data.v2.models.reports import (  # noqa: E402
    AggregateOutput,
    AggregateType,
    BudgetSummary,
    ChangeAggregate,
    CongressionalDistrictImpact,
    ConstituencyImpact,
    DecileImpact,
    DecileType,
    Inequality,
    IntraDecileImpact,
    LocalAuthorityImpact,
    OutputStatus,
    Poverty,
    ProgramStatistics,
    Report,
    ReportRun,
    ReportRunStatus,
    ReportRunTrigger,
)


V2_METADATA = SQLModel.metadata
validate_v2_metadata_table_names(V2_METADATA.tables)

__all__ = [
    "AggregateOutput",
    "AggregateType",
    "BudgetSummary",
    "ChangeAggregate",
    "CongressionalDistrictImpact",
    "ConstituencyImpact",
    "Dataset",
    "DatasetVersion",
    "DecileImpact",
    "DecileType",
    "Dynamic",
    "Household",
    "HouseholdJob",
    "HouseholdJobStatus",
    "Inequality",
    "IntraDecileImpact",
    "LocalAuthorityImpact",
    "LegacyPolicyMapping",
    "LegacyUserPolicyMapping",
    "OutputStatus",
    "Parameter",
    "ParameterNode",
    "ParameterValue",
    "Policy",
    "Poverty",
    "ProgramStatistics",
    "Region",
    "RegionType",
    "Report",
    "ReportRun",
    "ReportRunStatus",
    "ReportRunTrigger",
    "Simulation",
    "SimulationStatus",
    "SimulationType",
    "TaxBenefitModel",
    "TaxBenefitModelVersion",
    "User",
    "UserHouseholdAssociation",
    "UserPolicy",
    "UserReportAssociation",
    "UserSimulationAssociation",
    "V2_METADATA",
    "Variable",
]
