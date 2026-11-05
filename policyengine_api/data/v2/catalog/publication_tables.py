"""The v2 catalog tables that publication compares with and inserts into."""

from __future__ import annotations

from policyengine_api.data.v2.models import (
    Dataset,
    Parameter,
    ParameterNode,
    ParameterValue,
    Region,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)

DATASETS = Dataset.__table__
MODELS = TaxBenefitModel.__table__
MODEL_VERSIONS = TaxBenefitModelVersion.__table__
PARAMETERS = Parameter.__table__
PARAMETER_NODES = ParameterNode.__table__
PARAMETER_VALUES = ParameterValue.__table__
REGIONS = Region.__table__
VARIABLES = Variable.__table__
