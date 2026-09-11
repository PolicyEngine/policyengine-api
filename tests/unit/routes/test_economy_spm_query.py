"""Real Flask economy requests validate JSON selections before service dispatch."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask
import pytest

from policyengine_api import spm
from policyengine_api.routes import economy_routes
from policyengine_api.services.economy_service import EconomyService


@pytest.fixture(params=[False, True], ids=["annual", "budget-window"])
def economy_http(request, monkeypatch):
    budget_window = request.param
    defaults = {
        "forecast_content_sha256": "a" * 64,
        "scenario": "baseline",
        "geography_kind": "county",
    }
    monkeypatch.setattr(
        spm, "_current_bundle", lambda: {"measurements": {"spm": defaults}}
    )
    monkeypatch.setattr(spm, "simulation_supports_spm", lambda _: True)
    monkeypatch.setattr(
        spm,
        "_selected_forecast",
        lambda _: SimpleNamespace(years=[2026], entry=lambda *args, **kwargs: {}),
    )
    gateway = Mock()
    gateway.get_spm_capability.return_value = {
        "contract_version": "canonical-spm-v1",
        "defaults": defaults,
    }
    service = EconomyService(simulation_entrypoint_=gateway)
    setups = []

    def calculate(**kwargs):
        # Keep the actual service's selection and worker-capability boundary;
        # stop before database/cache access and computational submission.
        kwargs["time_period"] = kwargs.pop("start_year", kwargs.get("time_period"))
        kwargs.pop("window_size", None)
        setup = service._build_economic_impact_setup_options(**kwargs)
        setups.append(setup)
        return SimpleNamespace(
            cache_status=None,
            to_dict=lambda: {
                "status": "computing",
                "message": None,
                "data": None,
                "progress": 0,
                "completed_years": [],
                "computing_years": [],
                "queued_years": [],
                "error": None,
            },
        )

    dispatch = Mock(side_effect=calculate)
    method = (
        "get_budget_window_economic_impact" if budget_window else "get_economic_impact"
    )
    monkeypatch.setattr(economy_routes.economy_service, method, dispatch)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(economy_routes.economy_bp)
    path = "/us/economy/123/over/456"
    query = [("region", "us")]
    if budget_window:
        path += "/budget-window"
        query += [("start_year", "2026"), ("window_size", "2")]
    else:
        query += [("time_period", "2026")]
    return app.test_client(), path, query, dispatch, gateway, setups


def test_json_spm_selection_reaches_real_worker_validation(economy_http):
    client, path, query, dispatch, gateway, setups = economy_http
    response = client.get(
        path, query_string=query + [("spm", json.dumps({"geography_kind": "national"}))]
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "computing"
    assert dispatch.call_args.kwargs["options"] == {
        "spm": {"geography_kind": "national"}
    }
    assert setups[0].options["spm"]["geography_kind"] == "national"
    gateway.get_spm_capability.assert_called_once()
    gateway.run.assert_not_called()
    gateway.run_budget_window_batch.assert_not_called()


@pytest.mark.parametrize(
    "value",
    [
        "{",
        "null",
        "[]",
        '"national"',
        '{"unknown":true}',
        '{"geography_kind":"metro"}',
        '{"as_of":"2026-02-30"}',
        '{"geography_kind":"national","geography_kind":"county"}',
    ],
)
def test_malformed_spm_query_never_dispatches(economy_http, value):
    client, path, query, dispatch, gateway, _ = economy_http
    response = client.get(path, query_string=query + [("spm", value)])
    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == "SPM_SETTINGS_INVALID"
    dispatch.assert_not_called()
    gateway.get_spm_capability.assert_not_called()


@pytest.mark.parametrize("field", ["spm", "region", "dataset", "version", "target"])
def test_duplicate_scalar_economy_queries_never_dispatch(economy_http, field):
    client, path, query, dispatch, gateway, _ = economy_http
    query = [(key, value) for key, value in query if key != field]
    response = client.get(path, query_string=query + [(field, "{}"), (field, "{}")])
    assert response.status_code == 400
    assert "must not be repeated" in response.get_json()["message"]
    dispatch.assert_not_called()
    gateway.get_spm_capability.assert_not_called()


def test_unknown_economy_query_never_dispatches(economy_http):
    client, path, query, dispatch, _, _ = economy_http
    response = client.get(path, query_string=query + [("spmm", "{}")])
    assert response.status_code == 400
    assert "spmm" in response.get_json()["message"]
    dispatch.assert_not_called()


def test_economy_required_query_fields_are_rejected_before_dispatch(economy_http):
    client, path, query, dispatch, _, _ = economy_http
    for missing, _ in query:
        response = client.get(
            path, query_string=[pair for pair in query if pair[0] != missing]
        )
        assert response.status_code == 400
        assert missing in response.get_json()["message"]
    dispatch.assert_not_called()


def test_omitted_selection_and_query_defaults_are_preserved(economy_http):
    client, path, query, dispatch, _, setups = economy_http
    response = client.get(path, query_string=query)
    assert response.status_code == 200
    assert dispatch.call_args.kwargs["options"] == {}
    assert dispatch.call_args.kwargs["dataset"] == "default"
    assert dispatch.call_args.kwargs["target"] == "general"
    assert setups[0].options["spm"]["geography_kind"] == "county"


def test_every_required_and_deprecated_query_field_is_scalar(economy_http):
    client, path, query, dispatch, _, _ = economy_http
    for field, value in query + [("include_district_breakdowns", "true")]:
        duplicates = [(key, item) for key, item in query if key != field]
        duplicates += [(field, value), (field, value)]
        response = client.get(path, query_string=duplicates)
        assert response.status_code == 400
        assert "must not be repeated" in response.get_json()["message"]
    dispatch.assert_not_called()


@pytest.mark.parametrize("value", ["2.0", "0", "76", "abc"])
def test_invalid_numeric_query_values_never_dispatch(economy_http, value):
    client, path, query, dispatch, _, _ = economy_http
    field = "window_size" if path.endswith("/budget-window") else "time_period"
    query = [(key, item) for key, item in query if key != field]
    response = client.get(path, query_string=query + [(field, value)])
    assert response.status_code == 400
    dispatch.assert_not_called()


@pytest.mark.parametrize("value", ["", "2026.0", "no-year"])
def test_malformed_economy_years_never_dispatch(economy_http, value):
    client, path, query, dispatch, _, _ = economy_http
    field = "start_year" if path.endswith("/budget-window") else "time_period"
    query = [(key, item) for key, item in query if key != field]
    response = client.get(path, query_string=query + [(field, value)])
    assert response.status_code == 400
    dispatch.assert_not_called()


@pytest.mark.parametrize("version", ["5.2.1", "6.0.0"])
def test_bundle_version_bump_without_measurements_still_dispatches(
    economy_http, monkeypatch, version
):
    """An unconfigured bundle must not block economy requests that send no spm."""
    client, path, query, dispatch, gateway, _ = economy_http
    monkeypatch.setattr(
        spm,
        "_current_bundle",
        lambda: {
            "policyengine_version": version,
            "packages": {"policyengine-us": {"version": "1.764.6"}},
        },
    )
    monkeypatch.setattr(spm, "simulation_supports_spm", lambda _: False)
    response = client.get(path, query_string=query)
    assert response.status_code == 200, response.get_json()
    assert dispatch.call_args.kwargs["options"] == {}
    gateway.get_spm_capability.assert_not_called()


def test_canonical_model_without_certification_refuses_economy_requests(
    economy_http, monkeypatch
):
    client, path, query, dispatch, gateway, _ = economy_http
    monkeypatch.setattr(
        spm,
        "_current_bundle",
        lambda: {
            "policyengine_version": "5.2.0",
            "packages": {"policyengine-us": {"version": "1.764.6"}},
        },
    )
    monkeypatch.setattr(spm, "simulation_supports_spm", lambda _: True)
    response = client.get(path, query_string=query)
    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == "SPM_CONFIGURATION_UNAVAILABLE"
    gateway.get_spm_capability.assert_not_called()
