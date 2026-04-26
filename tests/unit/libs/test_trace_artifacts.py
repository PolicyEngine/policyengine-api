import pytest

from policyengine_api.libs.trace_artifacts import (
    TraceEmissionUnavailable,
    build_api_run_trace_artifacts,
    build_runtime_environment,
    build_runtime_payload,
)


RUNTIME_ENVIRONMENT_KEYS = (
    "GITHUB_SHA",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_REGION",
    "K_SERVICE",
    "K_REVISION",
    "GAE_SERVICE",
    "GAE_VERSION",
    "CONTAINER_IMAGE",
)

FAKE_BUNDLE_TRO = {
    "@context": [],
    "@graph": [
        {
            "@type": "trov:TransparentResearchObject",
            "schema:name": "policyengine us certified bundle TRO",
            "trov:createdWith": {
                "schema:name": "policyengine",
                "schema:softwareVersion": "4.4.0",
            },
            "trov:hasComposition": {
                "trov:hasFingerprint": {
                    "trov:sha256": "bundle-fingerprint",
                }
            },
        }
    ],
}


def clear_runtime_environment(monkeypatch):
    for key in RUNTIME_ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_build_api_run_trace_artifacts_binds_api_payloads():
    calls = {}
    country_manifest = object()
    data_manifest = object()

    def bundle_builder(country_manifest_arg, data_release_manifest_arg, **kwargs):
        calls["bundle"] = {
            "country_manifest": country_manifest_arg,
            "data_release_manifest": data_release_manifest_arg,
            "kwargs": kwargs,
        }
        return FAKE_BUNDLE_TRO

    def simulation_builder(**kwargs):
        calls["simulation"] = kwargs
        return {"simulation_tro": True, "simulation_id": kwargs["simulation_id"]}

    results_payload = {"budget": {"baseline": 1, "reform": 2}}
    reform_payload = {"gov.tax.income_tax.rate": {"2026-01-01.2100-12-31": 0.2}}
    input_payload = {"country": "us", "scope": "macro"}
    request_payload = {"path": "/economy/us/over/123", "method": "GET"}
    runtime_payload = {"service": "policyengine-api"}
    runtime_environment = {"cloudRunRevision": "policyengine-api-0001"}

    artifacts = build_api_run_trace_artifacts(
        country_id="us",
        results_payload=results_payload,
        reform_payload=reform_payload,
        input_payload=input_payload,
        request_payload=request_payload,
        runtime_payload=runtime_payload,
        runtime_environment=runtime_environment,
        simulation_id="run-123",
        bundle_tro_url="https://policyengine.org/traces/us/bundle.trace.tro.jsonld",
        release_manifest_resolver=lambda country_id: country_manifest,
        data_release_manifest_resolver=lambda country_id: data_manifest,
        bundle_tro_builder=bundle_builder,
        simulation_tro_builder=simulation_builder,
    )

    assert calls["bundle"]["country_manifest"] is country_manifest
    assert calls["bundle"]["data_release_manifest"] is data_manifest
    assert calls["bundle"]["kwargs"]["self_url"].startswith(
        "https://policyengine.org/traces/us/"
    )
    assert calls["simulation"]["bundle_tro"] == FAKE_BUNDLE_TRO
    assert calls["simulation"]["results_payload"] == results_payload
    assert calls["simulation"]["reform_payload"] == reform_payload
    assert calls["simulation"]["input_payload"] == input_payload
    assert calls["simulation"]["request_payload"] == request_payload
    assert calls["simulation"]["runtime_payload"] == runtime_payload
    assert calls["simulation"]["runtime_environment"] == runtime_environment
    assert calls["simulation"]["emission_context"] == {
        "pe:emittedIn": "policyengine-api"
    }
    assert artifacts.artifacts["request.json"] == request_payload
    assert artifacts.artifacts["runtime.json"] == runtime_payload
    assert artifacts.omitted_builder_fields == ()
    assert artifacts.bundle_tro_bytes().endswith(b"\n")
    assert artifacts.simulation_tro_bytes().endswith(b"\n")


def test_build_api_run_trace_artifacts_rejects_old_policyengine_builder():
    def old_simulation_builder(
        *,
        bundle_tro,
        results_payload,
        reform_payload=None,
        simulation_id=None,
    ):
        return {"simulation_tro": True}

    with pytest.raises(TraceEmissionUnavailable, match="does not support"):
        build_api_run_trace_artifacts(
            country_id="us",
            results_payload={"result": 1},
            input_payload={"country": "us"},
            request_payload={"path": "/economy/us/over/123"},
            runtime_payload={"service": "policyengine-api"},
            release_manifest_resolver=lambda country_id: object(),
            data_release_manifest_resolver=lambda country_id: object(),
            bundle_tro_builder=lambda country_manifest, data_release_manifest: (
                FAKE_BUNDLE_TRO
            ),
            simulation_tro_builder=old_simulation_builder,
        )


def test_build_api_run_trace_artifacts_can_report_degraded_builder_fields():
    def old_simulation_builder(*, bundle_tro, results_payload, simulation_id=None):
        return {"simulation_tro": True}

    artifacts = build_api_run_trace_artifacts(
        country_id="us",
        results_payload={"result": 1},
        input_payload={"country": "us"},
        request_payload={"path": "/economy/us/over/123"},
        runtime_payload={"service": "policyengine-api"},
        release_manifest_resolver=lambda country_id: object(),
        data_release_manifest_resolver=lambda country_id: object(),
        bundle_tro_builder=lambda country_manifest, data_release_manifest: (
            FAKE_BUNDLE_TRO
        ),
        simulation_tro_builder=old_simulation_builder,
        allow_degraded_builder=True,
    )

    assert artifacts.simulation_tro == {"simulation_tro": True}
    assert artifacts.omitted_builder_fields == (
        "emission_context",
        "input_payload",
        "request_payload",
        "runtime_payload",
    )


def test_build_runtime_payload_collects_runtime_environment(monkeypatch):
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("K_REVISION", "policyengine-api-0001")
    monkeypatch.setenv("GOOGLE_CLOUD_REGION", "us-central1")

    payload = build_runtime_payload(
        policyengine_bundle={"fingerprint": "sha256:abc"},
        run_context={"run_id": "run-123", "traceparent": None},
    )

    assert payload == {
        "service": "policyengine-api",
        "policyengine_bundle": {"fingerprint": "sha256:abc"},
        "run_context": {"run_id": "run-123"},
        "runtime_environment": {
            "cloudRegion": "us-central1",
            "cloudRunRevision": "policyengine-api-0001",
        },
    }


def test_build_runtime_environment_allows_explicit_overrides(monkeypatch):
    clear_runtime_environment(monkeypatch)
    monkeypatch.setenv("K_REVISION", "policyengine-api-0001")

    environment = build_runtime_environment(
        {"cloudRunRevision": "policyengine-api-0002", "empty": None}
    )

    assert environment == {"cloudRunRevision": "policyengine-api-0002"}
