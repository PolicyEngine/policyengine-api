"""Proof fixture: imports of removed simulation-domain models; the rule rejects it."""

# The household migration qualification imported these before the models were
# removed, and the report-run tests imported the report_runs module.
import policyengine_api.data.v2.models.retired_tables
from policyengine_api.data.v2.report_runs import ReportRunPackageVersions

from policyengine_api.data.v2 import report_runs
from policyengine_api.data.v2.models import (
    Household,
    HouseholdJob,
    Report,
    Simulation,
    UserHouseholdAssociation,
)

from . import report_runs as sibling_report_runs
from .models.simulations import SimulationStatus

__all__ = [
    "Household",
    "HouseholdJob",
    "Report",
    "ReportRunPackageVersions",
    "Simulation",
    "SimulationStatus",
    "UserHouseholdAssociation",
    "policyengine_api",
    "report_runs",
    "sibling_report_runs",
]
