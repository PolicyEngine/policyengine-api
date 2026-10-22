"""Proof fixture: kept v2 models and a same-named v1 model; the rule accepts it."""

from policyengine_api.data.v1_models import Simulation
from policyengine_api.data.v2.models import Household, Policy, UserReportAssociation

__all__ = ["Household", "Policy", "Simulation", "UserReportAssociation"]
