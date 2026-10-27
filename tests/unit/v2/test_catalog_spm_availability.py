"""Each catalog version's SPM availability, from the simulation service's versions."""

from __future__ import annotations

import httpx
import pytest

from policyengine_api.data.v2.catalog import spm_availability
from policyengine_api.data.v2.catalog.publication_types import CatalogPublicationError
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.spm import SPMSelection

POLICYENGINE_VERSION = "6.10.0"
DEFAULTS = {
    "forecast_content_sha256": "3d" * 32,
    "scenario": "ce_trend",
    "geography_kind": "county",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
VERSIONS = {
    "policyengine": {"latest": POLICYENGINE_VERSION},
    "spm_capabilities": {
        POLICYENGINE_VERSION: {
            "contract_version": "canonical-spm-v1",
            "defaults": DEFAULTS,
        }
    },
}


def test_a_us_version_with_a_certified_capability_offers_spm() -> None:
    availability = spm_availability.spm_availability(
        "us", POLICYENGINE_VERSION, VERSIONS
    )

    assert availability == {
        "available": True,
        "settings_schema": SPMSelection.model_json_schema(),
        "defaults": DEFAULTS,
    }


@pytest.mark.parametrize(
    ("country_id", "policyengine_version", "versions"),
    [
        ("uk", POLICYENGINE_VERSION, VERSIONS),
        ("us", "6.11.0", VERSIONS),
        ("us", POLICYENGINE_VERSION, {}),
        ("us", POLICYENGINE_VERSION, {"spm_capabilities": []}),
        (
            "us",
            POLICYENGINE_VERSION,
            {
                "spm_capabilities": {
                    POLICYENGINE_VERSION: {
                        "contract_version": "canonical-spm-v0",
                        "defaults": DEFAULTS,
                    }
                }
            },
        ),
        (
            "us",
            POLICYENGINE_VERSION,
            {
                "spm_capabilities": {
                    POLICYENGINE_VERSION: {
                        "contract_version": "canonical-spm-v1",
                        "defaults": {**DEFAULTS, "scenario": None},
                    }
                }
            },
        ),
    ],
    ids=[
        "uk",
        "unlisted-version",
        "no-capabilities",
        "malformed-capabilities",
        "other-contract",
        "unpinned-defaults",
    ],
)
def test_anything_else_offers_no_spm(
    country_id: str, policyengine_version: str, versions: object
) -> None:
    assert spm_availability.spm_availability(
        country_id, policyengine_version, versions
    ) == {"available": False}


def test_the_versions_come_from_the_simulation_services_public_route() -> None:
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=VERSIONS)

    with httpx.Client(transport=httpx.MockTransport(answer)) as client:
        versions = spm_availability.fetch_simulation_versions(
            "https://simulation.example/", client=client
        )

    assert versions == VERSIONS
    assert [str(request.url) for request in requests] == [
        "https://simulation.example/versions"
    ]
    assert "authorization" not in requests[0].headers


def test_an_unreadable_versions_answer_stops_the_recording() -> None:
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(503))
        ) as client,
        pytest.raises(CatalogPublicationError, match="versions"),
    ):
        spm_availability.fetch_simulation_versions(
            "https://simulation.example", client=client
        )


def test_recording_needs_the_simulation_service_url() -> None:
    with pytest.raises(V2ConfigurationError, match="SIMULATION_ENTRYPOINT_URL"):
        spm_availability.simulation_entrypoint_url({})

    assert (
        spm_availability.simulation_entrypoint_url(
            {"SIMULATION_ENTRYPOINT_URL": " https://simulation.example/ "}
        )
        == "https://simulation.example"
    )
