"""PolicyService checks a new policy's parameter paths against a parameter catalog."""

import pytest

from policyengine_api.data.v1_models import Policy
from policyengine_api.services.policy_service import (
    PolicyService,
    UnsettableParameterPathsError,
)
from policyengine_api.utils import hash_object

SETTABLE_NAMES = frozenset({"gov.tax.rate", "gov.tax.brackets[0].rate"})


class RecordingParameterCatalog:
    """Settable parameter names for every country, recording each lookup."""

    def __init__(self) -> None:
        self.looked_up_country_ids: list[str] = []

    def __call__(self, country_id: str) -> frozenset[str]:
        self.looked_up_country_ids.append(country_id)
        return SETTABLE_NAMES


@pytest.fixture
def parameter_catalog():
    return RecordingParameterCatalog()


@pytest.fixture
def service(orm_session_factory, parameter_catalog):
    return PolicyService(
        orm_session_factory,
        model_parameter_names=parameter_catalog,
    )


def test_new_policy_with_paths_outside_the_catalog_is_refused_and_not_stored(
    service,
    parameter_catalog,
):
    with pytest.raises(UnsettableParameterPathsError) as raised:
        service.set_policy(
            "US",
            "Refused",
            {
                "gov.tax": {"2026-01-01.2026-12-31": 1},
                "gov.tax.rate": {"2026-01-01.2026-12-31": 0.2},
                "gov.x": {"2026-01-01.2026-12-31": 1},
            },
        )

    assert raised.value.country_id == "us"
    assert raised.value.parameter_paths == ("gov.tax", "gov.x")
    assert [entry["path"] for entry in raised.value.error_entries] == [
        "data.gov.tax",
        "data.gov.x",
    ]
    assert parameter_catalog.looked_up_country_ids == ["us"]
    assert service.search_policies("us", "Refused") == []


def test_new_policy_with_catalog_paths_is_stored(service):
    policy_json = {
        "gov.tax.rate": {"2026-01-01.2026-12-31": 0.2},
        "gov.tax.brackets[0].rate": {"2026-01-01.2026-12-31": 0.1},
    }

    result = service.set_policy("us", "Accepted", policy_json)

    assert result.is_existing_policy is False
    assert service.get_policy_json("us", result.policy_id) == policy_json


def test_existing_identical_policy_is_returned_without_checking_its_paths(
    service,
    orm_session_factory,
    parameter_catalog,
):
    removed_parameter_policy = {"gov.removed": {"2026-01-01.2026-12-31": 1}}
    with orm_session_factory.begin() as session:
        session.add(
            Policy(
                id=98768,
                country_id="us",
                label="Stored",
                api_version="2.0.0",
                policy_json=removed_parameter_policy,
                policy_hash=hash_object(removed_parameter_policy),
            )
        )

    result = service.set_policy("us", "Stored", removed_parameter_policy)

    assert result.is_existing_policy is True
    assert result.policy_id == 98768
    assert parameter_catalog.looked_up_country_ids == []


def test_new_policy_for_a_country_without_a_loaded_model_is_refused(
    orm_session_factory,
):
    service_without_model = PolicyService(
        orm_session_factory,
        model_parameter_names=lambda _country_id: None,
    )

    with pytest.raises(UnsettableParameterPathsError) as raised:
        service_without_model.set_policy(
            "us",
            "No loaded model",
            {"gov.tax.rate": {"2026-01-01.2026-12-31": 0.2}},
        )

    assert raised.value.parameter_paths == ("gov.tax.rate",)
    assert service_without_model.search_policies("us", "No loaded model") == []
