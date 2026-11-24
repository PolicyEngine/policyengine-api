"""Controlled imports and metadata export for the reviewed v2 schema."""

from sqlmodel import SQLModel
from sqlmodel.main import default_registry

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
    UserReportRunAssociation,
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
from policyengine_api.data.v2.models.countries import Country  # noqa: E402
from policyengine_api.data.v2.models.household_mappings import (  # noqa: E402
    LegacyHouseholdMapping,
)
from policyengine_api.data.v2.models.households import (  # noqa: E402
    Household,
    HouseholdJob,
    HouseholdJobStatus,
)
from policyengine_api.data.v2.models.metadata import (  # noqa: E402
    CatalogEntity,
    CatalogEnumValue,
    Dataset,
    DatasetVersion,
    Parameter,
    ParameterNode,
    ParameterSearchFile,
    ParameterTreeChild,
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
from policyengine_api.data.v2.models.reports import (  # noqa: E402
    BudgetWindowRun,
    Report,
    ReportRun,
    ReportRunStatus,
    ReportRunTrigger,
)
from policyengine_api.data.v2.models.run_results import (  # noqa: E402  # tables declared after the naming convention above
    AggregateOutput,
    AggregateType,
    BudgetSummary,
    ChangeAggregate,
    CliffImpact,
    CongressionalDistrictImpact,
    ConstituencyImpact,
    DecileImpact,
    DecileType,
    Inequality,
    IntraDecileImpact,
    LaborSupplyDecileResponse,
    LaborSupplyResponse,
    LocalAuthorityImpact,
    OutputStatus,
    Poverty,
    ProgramStatistics,
    UKAreaType,
    WithheldAreaCode,
)
from policyengine_api.data.v2.models.simulations import (  # noqa: E402
    Simulation,
    SimulationRun,
    SimulationStatus,
    SimulationType,
)
from policyengine_api.data.v2.models.users import (  # noqa: E402
    INVITATION_USER_TYPES,
    SIGNED_IN_USER_TYPES,
    User,
    UserIdentity,
    UserInvitation,
    UserType,
    UserTypeChange,
    UserTypeChangeSource,
)

V2_METADATA = SQLModel.metadata
# The registry that maps the v2 table classes: SQLModel's own, whose metadata is
# V2_METADATA. Every v2 table has a mapped class (rule api.data.orm-only), so
# V2_TABLE_NAMES, the tables its classes map, are all of V2_METADATA's tables.
V2_REGISTRY = default_registry
V2_TABLE_NAMES = frozenset(
    mapper.class_.__tablename__ for mapper in V2_REGISTRY.mappers
)
validate_v2_metadata_table_names(V2_TABLE_NAMES)

__all__ = [
    "INVITATION_USER_TYPES",
    "SIGNED_IN_USER_TYPES",
    "V2_METADATA",
    "V2_REGISTRY",
    "V2_TABLE_NAMES",
    "AggregateOutput",
    "AggregateType",
    "BudgetSummary",
    "BudgetWindowRun",
    "CatalogEntity",
    "CatalogEnumValue",
    "ChangeAggregate",
    "CliffImpact",
    "CongressionalDistrictImpact",
    "ConstituencyImpact",
    "Country",
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
    "LaborSupplyDecileResponse",
    "LaborSupplyResponse",
    "LegacyHouseholdMapping",
    "LegacyPolicyMapping",
    "LegacyUserMapping",
    "LegacyUserPolicyMapping",
    "LocalAuthorityImpact",
    "OutputStatus",
    "Parameter",
    "ParameterNode",
    "ParameterSearchFile",
    "ParameterTreeChild",
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
    "SimulationRun",
    "SimulationStatus",
    "SimulationType",
    "Stage12AggregationStatus",
    "Stage12ComparisonReport",
    "Stage12ComparisonSimulation",
    "Stage12ResultComparisonStatus",
    "Stage12RunStatus",
    "Stage12SimulationRole",
    "TaxBenefitModel",
    "TaxBenefitModelVersion",
    "UKAreaType",
    "User",
    "UserHouseholdAssociation",
    "UserIdentity",
    "UserInvitation",
    "UserPolicy",
    "UserReportAssociation",
    "UserReportRunAssociation",
    "UserSimulationAssociation",
    "UserType",
    "UserTypeChange",
    "UserTypeChangeSource",
    "Variable",
    "WithheldAreaCode",
]
