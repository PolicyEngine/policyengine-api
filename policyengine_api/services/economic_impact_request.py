"""The request the economy routes pass to the economy service."""

from dataclasses import dataclass
from typing import Literal

# The one breakdown the annual economy route can request: the UK
# constituency and local-authority impacts, computed apart from the national
# result. The query model, the simulation payload and the service share it.
LocalAreaBreakdown = Literal["local_areas"]
LOCAL_AREA_BREAKDOWN: LocalAreaBreakdown = "local_areas"


@dataclass(frozen=True)
class EconomicImpactRequest:
    """One economic impact request: the policies, place, dataset and options.

    ``policy_id`` is the reform and ``baseline_policy_id`` the policy it is
    compared with. ``api_version`` is the country model version the caller asked
    for, which selects the cache generation; None means the installed version.
    """

    country_id: str
    policy_id: int
    baseline_policy_id: int
    region: str
    dataset: str
    options: dict
    api_version: str | None
    target: Literal["general", "cliff"] = "general"
