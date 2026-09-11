"""SPM cannot be cached or submitted to a worker without a certified contract."""

from unittest.mock import Mock, patch

import pytest
from flask import Flask

from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient
from policyengine_api.routes.economy_routes import economy_bp
from policyengine_api.services.economy_service import EconomyService
from policyengine_api.spm import SPMValidationError
from policyengine_api.worker_spm import validate_worker_spm


@pytest.mark.parametrize("selection", [None, {"geography_kind": "national"}])
def test_canonical_worker_selection_is_rejected_including_resolved_default(selection):
    with patch(
        "policyengine_api.worker_spm.normalize_spm_selection",
        return_value={"geography_kind": "national"},
    ) as normalize:
        with pytest.raises(SPMValidationError) as error:
            validate_worker_spm("us", selection)
    normalize.assert_called_once_with("us", selection)
    assert error.value.code == "SPM_CONFIGURATION_UNAVAILABLE"


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_legacy_worker_selection_remains_usable(country_id):
    with patch(
        "policyengine_api.worker_spm.normalize_spm_selection", return_value=None
    ):
        assert validate_worker_spm(country_id) is None


@pytest.mark.parametrize("country_id", ["us", "US", "uk"])
def test_actual_settings_validator_rejects_explicit_settings_on_legacy_worker(
    country_id,
):
    with patch(
        "policyengine_api.spm._current_bundle",
        return_value={
            "policyengine_version": "5.2.0",
            "packages": {"policyengine-us": {"version": "1.764.6"}},
        },
    ):
        assert validate_worker_spm(country_id) is None
        with pytest.raises(SPMValidationError) as error:
            validate_worker_spm(country_id, {"geography_kind": "national"})
    assert error.value.code == "SPM_SETTINGS_UNSUPPORTED"


@pytest.mark.parametrize("country_id", ["us", "US"])
def test_uncertified_canonical_bundle_cannot_default_to_legacy_worker(country_id):
    """A model that can run canonical SPM never reaches a worker uncertified."""
    with patch("policyengine_api.spm._current_bundle", return_value={}):
        with patch("policyengine_api.spm.simulation_supports_spm", return_value=True):
            with pytest.raises(SPMValidationError) as error:
                validate_worker_spm(country_id)
    assert error.value.code == "SPM_CONFIGURATION_UNAVAILABLE"


@pytest.mark.parametrize("country_id", ["us", "US"])
def test_unconfigured_bundle_keeps_the_legacy_worker_path(country_id):
    """An unconfigured bundle whose model predates the contract stays legacy.

    No worker capability is consulted, so an automated bundle bump cannot stall
    every economy request.
    """
    gateway = Mock()
    with patch("policyengine_api.spm._current_bundle", return_value={}):
        with patch("policyengine_api.spm.simulation_supports_spm", return_value=False):
            assert validate_worker_spm(country_id, gateway=gateway) is None
            with pytest.raises(SPMValidationError) as error:
                validate_worker_spm(country_id, {"geography_kind": "national"})
    assert error.value.code == "SPM_SETTINGS_UNSUPPORTED"
    gateway.get_spm_capability.assert_not_called()


@pytest.mark.parametrize("budget_window", [False, True])
@pytest.mark.parametrize("options", [{}, {"spm": {"geography_kind": "national"}}])
def test_canonical_economy_request_fails_before_cache_lookup(budget_window, options):
    service = EconomyService(
        budget_window_cache_=Mock(),
        reform_impacts_service_=Mock(),
        simulation_entrypoint_=Mock(),
    )
    arguments = {
        "country_id": "us",
        "policy_id": 1,
        "baseline_policy_id": 2,
        "region": "us",
        "dataset": "default",
        "options": options,
        "api_version": "test",
    }
    if budget_window:
        call = service.get_budget_window_economic_impact
        arguments.update(start_year="2026", window_size=2)
    else:
        call = service.get_economic_impact
        arguments["time_period"] = "2026"

    with patch(
        "policyengine_api.worker_spm.normalize_spm_selection",
        return_value={"geography_kind": "county"},
    ):
        with pytest.raises(SPMValidationError):
            call(**arguments)

    assert not service._injected_budget_window_cache.mock_calls
    assert not service._injected_reform_impacts_service.mock_calls
    service._injected_simulation_entrypoint.run.assert_not_called()
    service._injected_simulation_entrypoint.run_budget_window_batch.assert_not_called()


@pytest.mark.parametrize("method", ["run", "run_budget_window_batch"])
@pytest.mark.parametrize("selection", [None, {"geography_kind": "national"}])
def test_canonical_direct_submission_fails_before_transport(method, selection):
    client = object.__new__(SimulationEntrypointClient)
    client.client = Mock()
    client.get_spm_capability = Mock(return_value=None)
    payload = {"country": "us"}
    if selection is not None:
        payload["spm"] = selection

    with patch(
        "policyengine_api.worker_spm.normalize_spm_selection",
        return_value={"geography_kind": "county"},
    ):
        with pytest.raises(SPMValidationError):
            getattr(client, method)(payload)

    client.client.post.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        "/us/economy/1/over/2?region=us&time_period=2026",
        "/us/economy/1/over/2/budget-window?region=us&start_year=2026&window_size=2",
    ],
)
def test_canonical_economy_errors_use_existing_validation_envelope(path):
    app = Flask(__name__)
    app.register_blueprint(economy_bp)
    app.config["TESTING"] = True
    with patch(
        "policyengine_api.worker_spm.normalize_spm_selection",
        return_value={"geography_kind": "county"},
    ):
        with patch.object(
            SimulationEntrypointClient, "get_spm_capability", return_value=None
        ):
            response = app.test_client().get(path)

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["result"] is None
    assert payload["errors"] == [
        {
            "code": "SPM_CONFIGURATION_UNAVAILABLE",
            "message": payload["message"],
        }
    ]


SELECTION = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "ce_trend",
    "geography_kind": "national",
    "geography_id": None,
    "county_vintage": "2020",
    "as_of": None,
}
CAPABILITY = {"contract_version": "canonical-spm-v1", "defaults": SELECTION}


def test_certified_worker_selection_enters_identity_and_submission():
    gateway = Mock()
    gateway.get_spm_capability.return_value = CAPABILITY
    service = EconomyService(simulation_entrypoint_=gateway)
    with patch(
        "policyengine_api.worker_spm.normalize_spm_selection", return_value=SELECTION
    ):
        setup = service._build_economic_impact_setup_options(
            country_id="us",
            policy_id=1,
            baseline_policy_id=2,
            region="us",
            dataset="default",
            time_period="2026",
            options={},
            api_version="test",
        )
    assert setup.options["spm"] == SELECTION
    changed = {**SELECTION, "scenario": "zero_real"}
    assert service._build_options_hash(
        options={"spm": SELECTION}, model_version="test", dataset="default"
    ) != service._build_options_hash(
        options={"spm": changed}, model_version="test", dataset="default"
    )
    options = service._setup_sim_options("us", {}, {}, "us", "2026", spm=SELECTION)
    assert options.model_dump(mode="json")["spm"] == SELECTION


@pytest.mark.parametrize(
    "capability",
    [
        None,
        {**CAPABILITY, "contract_version": "future-unsupported"},
        {
            "contract_version": "canonical-spm-v1",
            "defaults": {**SELECTION, "forecast_content_sha256": "b" * 64},
        },
    ],
)
def test_uncertified_or_mismatching_worker_is_rejected(capability):
    gateway = Mock()
    gateway.get_spm_capability.return_value = capability
    with patch(
        "policyengine_api.worker_spm.normalize_spm_selection", return_value=SELECTION
    ):
        with pytest.raises(SPMValidationError):
            validate_worker_spm("us", gateway=gateway, policyengine_version="test-only")


@pytest.mark.parametrize(
    "method,path",
    [
        ("run", "/simulate/economy/comparison"),
        ("run_budget_window_batch", "/simulate/economy/budget-window"),
    ],
)
def test_actual_entrypoint_http_preserves_selection_and_data_version(method, path):
    import httpx
    import json

    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path == "/versions":
            return httpx.Response(
                200,
                json={
                    "policyengine": {"test-only": "test-app"},
                    "spm_capabilities": {"test-only": CAPABILITY},
                },
            )
        assert request.url.path == path
        body = json.loads(request.content)
        assert body["spm"] == SELECTION
        assert body["data_version"] == "selected-data"
        return httpx.Response(
            200, json={"job_id": "job", "batch_job_id": "batch", "status": "submitted"}
        )

    client = object.__new__(SimulationEntrypointClient)
    client.base_url = "http://test"
    client.client = httpx.Client(transport=httpx.MockTransport(handle))
    with patch(
        "policyengine_api.worker_spm.normalize_spm_selection", return_value=SELECTION
    ):
        getattr(client, method)(
            {
                "country": "us",
                "policyengine_version": "test-only",
                "data_version": "selected-data",
                "spm": {"geography_kind": "national"},
            }
        )
    assert [request.method for request in requests] == ["GET", "POST"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"policyengine_version": "test-only"},
        {"policyengine_version": "latest"},
        {"version": "country-test"},
        {"version": "latest"},
        {},
    ],
)
def test_worker_capability_uses_bundle_version_for_actual_registry_shape(kwargs):
    import httpx

    versions = {
        "policyengine": {"test-only": "test-app", "latest": "test-only"},
        "us": {"country-test": "test-app", "latest": "country-test"},
        "spm_capabilities": {"test-only": CAPABILITY},
    }
    client = object.__new__(SimulationEntrypointClient)
    client.base_url = "http://test"
    client.client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=versions))
    )
    assert client.get_spm_capability("us", **kwargs) == CAPABILITY


@pytest.mark.parametrize("other_app", ["test-app", "unrelated-app"])
def test_country_capability_requires_an_unambiguous_bundle_route(other_app):
    import httpx

    versions = {
        "policyengine": {"first": other_app, "second": other_app},
        "us": {"country-test": "test-app"},
        "spm_capabilities": {"first": CAPABILITY, "second": CAPABILITY},
    }
    client = object.__new__(SimulationEntrypointClient)
    client.base_url = "http://test"
    client.client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=versions))
    )
    with pytest.raises(SPMValidationError) as error:
        client.get_spm_capability("us", "country-test")
    assert error.value.code == "SPM_CONFIGURATION_UNAVAILABLE"


def test_explicit_bundle_capability_does_not_inherit_another_bundles_capability():
    import httpx

    versions = {
        "policyengine": {"first": "test-app", "second": "test-app"},
        "spm_capabilities": {"second": CAPABILITY},
    }
    client = object.__new__(SimulationEntrypointClient)
    client.base_url = "http://test"
    client.client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=versions))
    )
    assert client.get_spm_capability("us", policyengine_version="first") is None


@pytest.mark.parametrize("method", ["run", "run_budget_window_batch"])
def test_canonical_direct_submission_forwards_the_validated_default_bundle(method):
    import httpx
    import json
    from policyengine_api.constants import POLICYENGINE_VERSION

    def handle(request):
        body = json.loads(request.content)
        assert body["policyengine_version"] == POLICYENGINE_VERSION
        return httpx.Response(
            200, json={"job_id": "job", "batch_job_id": "batch", "status": "submitted"}
        )

    client = object.__new__(SimulationEntrypointClient)
    client.base_url = "http://test"
    client.client = httpx.Client(transport=httpx.MockTransport(handle))
    with patch(
        "policyengine_api.libs.simulation_entrypoint.validate_worker_spm",
        return_value=SELECTION,
    ) as validate:
        getattr(client, method)({"country": "us"})
    assert validate.call_args.kwargs["policyengine_version"] == POLICYENGINE_VERSION


def test_canonical_submission_rejects_mutable_latest_bundle_alias():
    client = object.__new__(SimulationEntrypointClient)
    with patch(
        "policyengine_api.libs.simulation_entrypoint.validate_worker_spm",
        return_value=SELECTION,
    ):
        with pytest.raises(SPMValidationError, match="exact PolicyEngine version"):
            client._normalize_submission_payload(
                {"country": "us", "policyengine_version": "latest"}
            )


@pytest.mark.parametrize(
    "code",
    ["SPM_GEOGRAPHY_REQUIRED", "SPM_GEOGRAPHY_UNAVAILABLE", "SPM_COMPOSITION_REQUIRED"],
)
@pytest.mark.parametrize(
    "method", ["get_execution_by_id", "get_budget_window_batch_by_id"]
)
def test_typed_worker_poll_errors_reach_api_validation(code, method):
    import httpx

    client = object.__new__(SimulationEntrypointClient)
    client.base_url = "http://test"
    client.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400,
                json={
                    "status": "failed",
                    "result": None,
                    "error": "Explicit input required",
                    "errors": [{"code": code, "message": "Explicit input required"}],
                },
            )
        )
    )
    with pytest.raises(SPMValidationError) as error:
        getattr(client, method)("job")
    assert error.value.to_dict() == {"code": code, "message": "Explicit input required"}


def test_worker_cache_receipts_are_required_and_json_roundtrip():
    import json
    from policyengine_api.worker_spm import validate_worker_result

    receipt = dict(
        forecast_id="test-only",
        forecast_sha256=SELECTION["forecast_content_sha256"],
        scenario="ce_trend",
        geography_kind="national",
        runtime_versions={},
        years={"2026": {}},
        geographies=[],
        composition_method="classified-inputs",
        storage_method="formula",
    )
    output = {
        "spm_config": SELECTION,
        "spm_provenance": {"baseline": [receipt], "reform": [receipt]},
    }
    validate_worker_result(json.loads(json.dumps(output)), SELECTION)
    validate_worker_result(
        {
            **output,
            "spm_config": {
                key: value for key, value in SELECTION.items() if value is not None
            },
        },
        SELECTION,
    )
    validate_worker_result(
        {
            "kind": "budgetWindow",
            "windowSize": 1,
            "annualImpacts": [{"year": "2026", **output}],
        },
        SELECTION,
    )
    for incomplete in (
        {},
        {"spm_config": SELECTION},
        {**output, "spm_config": {**SELECTION, "scenario": "zero_real"}},
    ):
        with pytest.raises(SPMValidationError):
            validate_worker_result(incomplete, SELECTION)


@pytest.mark.parametrize(
    "missing",
    ["forecast_content_sha256", "scenario", "geography_kind", "county_vintage"],
)
def test_worker_receipt_cannot_inherit_nonnull_settings(missing):
    from policyengine_api.worker_spm import validate_worker_result

    config = {key: value for key, value in SELECTION.items() if key != missing}
    with pytest.raises(SPMValidationError, match="incomplete resolved"):
        validate_worker_result({"spm_config": config}, SELECTION)


@pytest.mark.parametrize("side", ["baseline", "reform"])
def test_worker_receipt_must_cover_requested_year(side):
    from policyengine_api.worker_spm import validate_worker_result

    receipt = {
        "forecast_id": "test-only",
        "forecast_sha256": SELECTION["forecast_content_sha256"],
        "scenario": "ce_trend",
        "geography_kind": "national",
        "runtime_versions": {},
        "years": {"2026": {}},
        "geographies": [],
        "composition_method": "classified",
        "storage_method": "formula",
    }
    result = {
        "spm_config": SELECTION,
        "spm_provenance": {
            "baseline": [dict(receipt)],
            "reform": [dict(receipt)],
        },
    }
    validate_worker_result(result, SELECTION, expected_year="2026")
    result["spm_provenance"][side][0]["years"] = {"2025": {}}
    with pytest.raises(SPMValidationError, match="requested year"):
        validate_worker_result(result, SELECTION, expected_year="2026")


@pytest.mark.parametrize(
    "years", [["2025", "2026"], ["2026", "2026"], ["2027", "2026"]]
)
def test_budget_result_cannot_swap_or_duplicate_requested_years(years):
    from policyengine_api.worker_spm import validate_worker_result

    output = {
        "kind": "budgetWindow",
        "windowSize": 2,
        "annualImpacts": [{"year": year} for year in years],
    }
    with pytest.raises(SPMValidationError, match="years differ"):
        validate_worker_result(output, SELECTION, expected_years=["2026", "2027"])


@pytest.mark.parametrize("result", [None, [], "invalid", 1])
def test_worker_result_requires_an_object(result):
    from policyengine_api.worker_spm import validate_worker_result

    with pytest.raises(SPMValidationError):
        validate_worker_result(result, SELECTION, expected_year="2026")


@pytest.mark.parametrize("rows", [[], [{"year": "2026"}]])
def test_annual_result_cannot_be_a_budget_window(rows):
    from policyengine_api.worker_spm import validate_worker_result

    with pytest.raises(SPMValidationError):
        validate_worker_result(
            {"kind": "budgetWindow", "windowSize": len(rows), "annualImpacts": rows},
            SELECTION,
            expected_year="2026",
        )


@pytest.mark.parametrize("rows", [None, {}, "x", [None], [[]], ["bad"]])
def test_budget_result_requires_annual_row_objects(rows):
    from policyengine_api.worker_spm import validate_worker_result

    with pytest.raises(SPMValidationError):
        validate_worker_result(
            {"kind": "budgetWindow", "windowSize": 1, "annualImpacts": rows},
            SELECTION,
            expected_years=["2026"],
        )


@pytest.mark.parametrize("size", [0, -1, True, "1", 1.0])
def test_budget_result_requires_positive_integer_window_size(size):
    from policyengine_api.worker_spm import validate_worker_result

    with pytest.raises(SPMValidationError):
        validate_worker_result(
            {
                "kind": "budgetWindow",
                "windowSize": size,
                "annualImpacts": [] if size == 0 else [annual_shape_result()],
            },
            SELECTION,
        )


def test_budget_result_cannot_nest_another_budget_window():
    from policyengine_api.worker_spm import validate_worker_result

    with pytest.raises(SPMValidationError):
        validate_worker_result(
            {
                "kind": "budgetWindow",
                "windowSize": 1,
                "annualImpacts": [
                    {"year": "2026", "kind": "budgetWindow", "windowSize": 0},
                ],
            },
            SELECTION,
            expected_years=["2026"],
        )


def annual_shape_result(year="2026"):
    receipt = {
        "forecast_id": "test-only",
        "forecast_sha256": SELECTION["forecast_content_sha256"],
        "scenario": SELECTION["scenario"],
        "geography_kind": SELECTION["geography_kind"],
        "runtime_versions": {},
        "years": {"2026": {}},
        "geographies": [],
        "composition_method": "classified",
        "storage_method": "formula",
    }
    return {
        "year": year,
        "spm_config": SELECTION,
        "spm_provenance": {"baseline": [receipt], "reform": [receipt]},
    }


@pytest.mark.parametrize("year", [None, {}, [], True, "", "2026.0"])
def test_budget_rows_require_calendar_year_even_without_requested_years(year):
    from policyengine_api.worker_spm import validate_worker_result

    with pytest.raises(SPMValidationError):
        validate_worker_result(
            {
                "kind": "budgetWindow",
                "windowSize": 1,
                "annualImpacts": [annual_shape_result(year)],
            },
            SELECTION,
        )


@pytest.mark.parametrize("year", ["2026", 2026])
def test_worker_valid_annual_and_window_shapes_cover_requested_year(year):
    from policyengine_api.worker_spm import validate_worker_result

    annual = annual_shape_result(year)
    validate_worker_result(annual, SELECTION, expected_year="2026")
    validate_worker_result(
        {"kind": "budgetWindow", "windowSize": 1, "annualImpacts": [annual]},
        SELECTION,
        expected_years=["2026"],
    )
