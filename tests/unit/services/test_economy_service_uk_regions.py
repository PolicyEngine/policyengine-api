"""UK economy regions are checked against .py's UK region registry up front.

A region the simulation service cannot resolve is refused while the request is
set up, before any cached result is written or any simulation is submitted.
"""

from unittest.mock import MagicMock, patch

import pytest
from policyengine.countries.uk.regions import build_uk_region_registry

from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_service import EconomyService
from tests.fixtures.services.economy_service import (
    MOCK_API_VERSION,
    MOCK_BASELINE_POLICY_ID,
    MOCK_POLICY_ID,
    MOCK_TIME_PERIOD,
)

pytest_plugins = ("tests.fixtures.services.economy_service",)
pytestmark = pytest.mark.usefixtures("stable_observability_lifecycle")

REGISTRY_LOADER = "policyengine_api.data.uk_regions.load_uk_region_registry"

# Production clients sent these on 2026-10-28. The Public API accepted them,
# and the simulation service then failed to resolve them.
UNRESOLVABLE_PRODUCTION_REGIONS = (
    "constituency",
    "parliamentary_constituency",
    "constituency/all",
)
# Production requests on the same day that the simulation service resolved.
RESOLVABLE_PRODUCTION_REGIONS = (
    "constituency/E14001063",
    "local_authority/E09000022",
    "constituency/Clapham and Brixton Hill",
)
# Spellings the simulation service normalises to a registry code.
RESOLVABLE_SPELLINGS = (
    "uk",
    "UK",
    " uk",
    "england",
    "Northern Ireland",
    "Country/Scotland",
    "country/wales ",
    "country/ni",
    "country/northern_ireland",
    "constituency/e14001063",
    "constituency/aldershot",
    "constituency/clapham and brixton hill",
    "local_authority/e09000022",
    "local_authority/Lambeth",
)
OTHER_UNRESOLVABLE_REGIONS = (
    "country/france",
    "country/NI",
    "country/",
    "state/ca",
    "us",
    "constituency/Nowhere",
    "local_authority/E99999999",
)

ACCEPTED_REGIONS = (
    "Accepted regions: uk; country/england, country/scotland, country/wales, "
    "country/northern_ireland or country/ni; "
    "constituency/<constituency name or GSS code>; "
    "local_authority/<local authority name or GSS code>."
)


def _uk_request(region: str, options: dict | None = None) -> EconomicImpactRequest:
    return EconomicImpactRequest(
        country_id="uk",
        policy_id=MOCK_POLICY_ID,
        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
        region=region,
        dataset="default",
        options=options or {},
        api_version=MOCK_API_VERSION,
    )


def _service_with_recorded_collaborators() -> tuple[EconomyService, MagicMock]:
    """Return a service whose cache, store and simulation calls are all recorded."""
    collaborators = MagicMock()
    service = EconomyService(
        policy_service_=collaborators.policies,
        reform_impacts_service_=collaborators.reform_impacts,
        budget_window_cache_=collaborators.budget_window_cache,
        simulation_entrypoint_=collaborators.simulation_entrypoint,
    )
    return service, collaborators


@pytest.mark.parametrize(
    "region", UNRESOLVABLE_PRODUCTION_REGIONS + OTHER_UNRESOLVABLE_REGIONS
)
def test_an_unresolvable_uk_region_is_refused_while_setting_up(region):
    service, collaborators = _service_with_recorded_collaborators()

    with (
        patch(
            "policyengine_api.services.economy_service.get_economy_impact_cache_version"
        ) as cache_version,
        pytest.raises(ValueError, match="Unknown UK region") as raised,
    ):
        service._build_economic_impact_setup_options(
            _uk_request(region), time_period=MOCK_TIME_PERIOD
        )

    assert str(raised.value) == f"Unknown UK region {region!r}. {ACCEPTED_REGIONS}"
    cache_version.assert_not_called()
    assert collaborators.mock_calls == []


@pytest.mark.parametrize("region", RESOLVABLE_PRODUCTION_REGIONS + RESOLVABLE_SPELLINGS)
def test_a_resolvable_uk_region_keeps_its_requested_spelling(region):
    service, _collaborators = _service_with_recorded_collaborators()

    setup_options = service._build_economic_impact_setup_options(
        _uk_request(region), time_period=MOCK_TIME_PERIOD
    )

    assert setup_options.region == region


@pytest.mark.parametrize("region", UNRESOLVABLE_PRODUCTION_REGIONS)
def test_an_annual_request_for_an_unresolvable_region_stores_and_submits_nothing(
    region,
):
    service, collaborators = _service_with_recorded_collaborators()

    with pytest.raises(ValueError, match="Unknown UK region"):
        service.get_economic_impact(_uk_request(region), time_period="2026")

    assert collaborators.mock_calls == []


@pytest.mark.parametrize("region", UNRESOLVABLE_PRODUCTION_REGIONS)
def test_a_budget_window_request_for_an_unresolvable_region_stores_and_submits_nothing(
    region,
):
    service, collaborators = _service_with_recorded_collaborators()

    with pytest.raises(ValueError, match="Unknown UK region"):
        service.get_budget_window_economic_impact(
            _uk_request(region), start_year="2026", window_size=3
        )

    assert collaborators.mock_calls == []


@pytest.mark.parametrize("region", UNRESOLVABLE_PRODUCTION_REGIONS)
def test_a_breakdown_request_for_an_unresolvable_region_stores_and_submits_nothing(
    region,
):
    service, collaborators = _service_with_recorded_collaborators()

    with pytest.raises(ValueError, match="breakdown=local_areas needs region uk"):
        service.get_economic_impact(
            _uk_request(region, {"breakdown": "local_areas"}), time_period="2026"
        )

    assert collaborators.mock_calls == []


def test_a_bundle_without_local_areas_refuses_area_regions():
    # .py registers constituencies and local authorities only when the bundle's
    # regional_release_kind is local_area; this is its registry otherwise.
    national_first_registry = build_uk_region_registry(
        include_constituencies=False, include_local_authorities=False
    )
    service, _collaborators = _service_with_recorded_collaborators()

    with patch(REGISTRY_LOADER, return_value=national_first_registry):
        accepted = service._build_economic_impact_setup_options(
            _uk_request("country/wales"), time_period=MOCK_TIME_PERIOD
        )
        with pytest.raises(ValueError, match="Unknown UK region") as raised:
            service._build_economic_impact_setup_options(
                _uk_request("constituency/E14001063"), time_period=MOCK_TIME_PERIOD
            )

    assert accepted.region == "country/wales"
    assert str(raised.value) == (
        "Unknown UK region 'constituency/E14001063'. Accepted regions: uk; "
        "country/england, country/scotland, country/wales, "
        "country/northern_ireland or country/ni."
    )


def test_the_national_region_needs_no_registry():
    service, _collaborators = _service_with_recorded_collaborators()

    with patch(REGISTRY_LOADER, side_effect=AssertionError("registry loaded")):
        setup_options = service._build_economic_impact_setup_options(
            _uk_request("uk"), time_period=MOCK_TIME_PERIOD
        )

    assert setup_options.region == "uk"


def test_a_us_request_is_not_checked_against_the_uk_registry():
    service, _collaborators = _service_with_recorded_collaborators()
    us_request = EconomicImpactRequest(
        country_id="us",
        policy_id=MOCK_POLICY_ID,
        baseline_policy_id=MOCK_BASELINE_POLICY_ID,
        region="state/ca",
        dataset="default",
        options={},
        api_version=MOCK_API_VERSION,
    )

    with (
        patch(REGISTRY_LOADER, side_effect=AssertionError("registry loaded")),
        # A US request also checks the worker's SPM capability, which this
        # test does not exercise.
        patch(
            "policyengine_api.services.economy_service.validate_worker_spm",
            return_value=None,
        ),
    ):
        setup_options = service._build_economic_impact_setup_options(
            us_request, time_period=MOCK_TIME_PERIOD
        )

    assert setup_options.region == "state/ca"
