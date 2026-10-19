"""Proof fixture: kept v2 models and a v1 model named like a removed one. The rule must accept it."""

from policyengine_api.data.v1_models import Simulation
from policyengine_api.data.v2.models import Policy, UserReportAssociation

__all__ = ["Policy", "Simulation", "UserReportAssociation"]
