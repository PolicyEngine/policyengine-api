"""The deployment smoke rejects canonical results without matching receipts."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from tests.integration.test_cloud_run_candidate import (
    test_cloud_run_candidate_current_law_economy as run_smoke,
)


@pytest.fixture
def smoke():
    defaults = {
        "forecast_content_sha256": "a" * 64,
        "scenario": "baseline",
        "geography_kind": "county",
    }
    metadata = {
        "current_law_id": 2,
        "economy_options": {"time_period": [{"name": "2025"}]},
        "spm": {"available": True, "defaults": defaults},
    }
    receipt = {
        "forecast_sha256": "a" * 64,
        "scenario": "baseline",
        "geography_kind": "county",
        "years": {"2025": {}},
    }
    result = {
        "budget": {"budgetary_impact": 0},
        "spm_config": defaults,
        "spm_provenance": {
            "baseline": [deepcopy(receipt)],
            "reform": [deepcopy(receipt)],
        },
    }
    client = SimpleNamespace(
        get=Mock(
            return_value=SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: {"result": metadata}
            )
        )
    )
    poll = Mock(return_value={"status": "ok", "result": result})
    return client, poll, metadata, result


def test_current_law_smoke_uses_no_policy_write(smoke):
    client, poll, _, _ = smoke
    run_smoke(client, poll)
    client.get.assert_called_once_with("/us/metadata")
    assert poll.call_args.args[1] == "/us/economy/2/over/2"
    query = poll.call_args.args[2]
    assert query["region"] == "ut"
    assert query["time_period"] == "2025"
    assert UUID(query["cache_nonce"]).version == 4


def test_each_current_law_smoke_has_a_fresh_cache_identity(smoke):
    client, poll, _, _ = smoke
    run_smoke(client, poll)
    run_smoke(client, poll)
    assert (
        poll.call_args_list[0].args[2]["cache_nonce"]
        != poll.call_args_list[1].args[2]["cache_nonce"]
    )


@pytest.mark.parametrize(
    "error", ["missing", "hash", "year", "budget", "nonzero-budget"]
)
def test_current_law_smoke_rejects_incomplete_worker_evidence(smoke, error):
    client, poll, _, result = smoke
    if error == "missing":
        result["spm_provenance"]["reform"] = []
    elif error == "hash":
        result["spm_provenance"]["reform"][0]["forecast_sha256"] = "b" * 64
    elif error == "year":
        result["spm_provenance"]["reform"][0]["years"] = {"2024": {}}
    elif error == "nonzero-budget":
        result["budget"]["budgetary_impact"] = 1
    else:
        result["budget"]["budgetary_impact"] = float("nan")
    with pytest.raises(AssertionError):
        run_smoke(client, poll)


def test_current_law_smoke_accepts_legacy_without_receipts(smoke):
    client, poll, metadata, result = smoke
    metadata["spm"] = {"available": False}
    del result["spm_provenance"]
    run_smoke(client, poll)


def test_current_law_smoke_accepts_only_null_setting_omissions(smoke):
    client, poll, metadata, result = smoke
    metadata["spm"]["defaults"] = {
        **metadata["spm"]["defaults"],
        "as_of": None,
        "geography_id": None,
    }
    run_smoke(client, poll)
    result["spm_config"] = {
        "forecast_content_sha256": "a" * 64,
        "geography_kind": "county",
    }
    with pytest.raises(AssertionError):
        run_smoke(client, poll)
