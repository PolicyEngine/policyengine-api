"""Build TRACE artifacts for PolicyEngine API simulation runs."""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from policyengine.provenance.manifest import (
    DataReleaseManifestUnavailableError,
    get_data_release_manifest,
    get_release_manifest,
)
from policyengine.provenance.trace import (
    build_simulation_trace_tro,
    build_trace_tro_from_release_bundle,
    canonical_json_bytes,
)


_RUN_BINDING_FIELDS = (
    "input_payload",
    "request_payload",
    "runtime_payload",
    "runtime_environment",
)

_RUNTIME_ENVIRONMENT_KEYS = {
    "GITHUB_SHA": "gitSha",
    "GOOGLE_CLOUD_PROJECT": "cloudProject",
    "GOOGLE_CLOUD_REGION": "cloudRegion",
    "K_SERVICE": "cloudRunService",
    "K_REVISION": "cloudRunRevision",
    "GAE_SERVICE": "appEngineService",
    "GAE_VERSION": "appEngineVersion",
    "CONTAINER_IMAGE": "containerImage",
}


class TraceEmissionUnavailable(RuntimeError):
    """Raised when the installed policyengine cannot emit a complete API TRO."""


@dataclass(frozen=True)
class TraceArtifactSet:
    """TRACE documents and the JSON payloads they bind."""

    bundle_tro: Mapping[str, Any]
    simulation_tro: Mapping[str, Any]
    artifacts: Mapping[str, Mapping[str, Any]]
    omitted_builder_fields: tuple[str, ...] = ()

    def bundle_tro_bytes(self) -> bytes:
        return canonical_json_bytes(self.bundle_tro)

    def simulation_tro_bytes(self) -> bytes:
        return canonical_json_bytes(self.simulation_tro)


def build_runtime_environment(
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect API runtime fields that should become TRO performance metadata."""

    environment = {
        target_key: os.environ[source_key]
        for source_key, target_key in _RUNTIME_ENVIRONMENT_KEYS.items()
        if os.environ.get(source_key)
    }
    if extra is not None:
        environment.update(_drop_none(extra))
    return environment


def build_runtime_payload(
    *,
    policyengine_bundle: Mapping[str, Any] | None,
    run_context: Mapping[str, Any] | None = None,
    runtime_environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the runtime.json payload hashed by the simulation TRO."""

    payload: dict[str, Any] = {
        "service": "policyengine-api",
        "policyengine_bundle": dict(policyengine_bundle or {}),
    }
    context = _drop_none(run_context)
    if context:
        payload["run_context"] = context

    environment = (
        dict(runtime_environment)
        if runtime_environment is not None
        else build_runtime_environment()
    )
    environment = _drop_none(environment)
    if environment:
        payload["runtime_environment"] = environment
    return payload


def build_api_run_trace_artifacts(
    *,
    country_id: str,
    results_payload: Mapping[str, Any],
    reform_payload: Mapping[str, Any] | None = None,
    reform_name: str | None = None,
    input_payload: Mapping[str, Any] | None = None,
    input_name: str | None = None,
    request_payload: Mapping[str, Any] | None = None,
    runtime_payload: Mapping[str, Any] | None = None,
    runtime_environment: Mapping[str, Any] | None = None,
    emission_context: Mapping[str, Any] | None = None,
    simulation_id: str | None = None,
    created_at: str | None = None,
    started_at: str | None = None,
    bundle_tro_url: str | None = None,
    bundle_tro_location: str | None = None,
    results_location: str | None = None,
    reform_location: str | None = None,
    input_location: str | None = None,
    request_location: str | None = None,
    runtime_location: str | None = None,
    release_manifest_resolver: Callable[[str], Any] = get_release_manifest,
    data_release_manifest_resolver: Callable[[str], Any] = get_data_release_manifest,
    bundle_tro_builder: Callable[..., Mapping[str, Any]] = (
        build_trace_tro_from_release_bundle
    ),
    simulation_tro_builder: Callable[..., Mapping[str, Any]] = (
        build_simulation_trace_tro
    ),
    allow_degraded_builder: bool = False,
) -> TraceArtifactSet:
    """Build TROs and canonical payloads for one policyengine-api run.

    ``allow_degraded_builder`` exists for tests and emergency migrations. The
    default is deliberately strict: if the installed ``policyengine`` cannot bind
    request/input/runtime payloads, the API must not emit an incomplete TRO that
    looks institutionally complete.
    """

    country_manifest = release_manifest_resolver(country_id)
    data_release_manifest = _resolve_data_release_manifest(
        country_id,
        data_release_manifest_resolver,
    )
    bundle_tro = _build_bundle_tro(
        bundle_tro_builder=bundle_tro_builder,
        country_manifest=country_manifest,
        data_release_manifest=data_release_manifest,
        bundle_tro_url=bundle_tro_url,
    )

    simulation_kwargs: dict[str, Any] = {
        "bundle_tro": bundle_tro,
        "results_payload": results_payload,
        "reform_payload": reform_payload,
        "reform_name": reform_name,
        "input_payload": input_payload,
        "input_name": input_name,
        "request_payload": request_payload,
        "runtime_payload": runtime_payload,
        "runtime_environment": runtime_environment,
        "emission_context": emission_context or {"pe:emittedIn": "policyengine-api"},
        "simulation_id": simulation_id,
        "created_at": created_at,
        "started_at": started_at,
        "results_location": results_location,
        "reform_location": reform_location,
        "input_location": input_location,
        "request_location": request_location,
        "runtime_location": runtime_location,
        "bundle_tro_location": bundle_tro_location,
        "bundle_tro_url": bundle_tro_url,
    }
    simulation_tro, omitted_builder_fields = _call_simulation_tro_builder(
        simulation_tro_builder,
        simulation_kwargs,
        allow_degraded_builder=allow_degraded_builder,
    )

    artifacts: dict[str, Mapping[str, Any]] = {
        "bundle.trace.tro.jsonld": bundle_tro,
        "results.json": results_payload,
    }
    if reform_payload is not None:
        artifacts["reform.json"] = reform_payload
    if input_payload is not None:
        artifacts["input.json"] = input_payload
    if request_payload is not None:
        artifacts["request.json"] = request_payload
    if runtime_payload is not None:
        artifacts["runtime.json"] = runtime_payload

    return TraceArtifactSet(
        bundle_tro=bundle_tro,
        simulation_tro=simulation_tro,
        artifacts=artifacts,
        omitted_builder_fields=omitted_builder_fields,
    )


def _resolve_data_release_manifest(
    country_id: str,
    data_release_manifest_resolver: Callable[[str], Any],
) -> Any | None:
    try:
        return data_release_manifest_resolver(country_id)
    except DataReleaseManifestUnavailableError:
        return None


def _build_bundle_tro(
    *,
    bundle_tro_builder: Callable[..., Mapping[str, Any]],
    country_manifest: Any,
    data_release_manifest: Any | None,
    bundle_tro_url: str | None,
) -> Mapping[str, Any]:
    kwargs: dict[str, Any] = {}
    if bundle_tro_url is not None and _callable_supports(
        bundle_tro_builder, "self_url"
    ):
        kwargs["self_url"] = bundle_tro_url

    try:
        return bundle_tro_builder(country_manifest, data_release_manifest, **kwargs)
    except Exception as exc:
        if data_release_manifest is None:
            raise TraceEmissionUnavailable(
                "Cannot build a bundle TRO without a data release manifest. "
                "Upgrade policyengine.py to a release with limited bundle TRO "
                "fallback support before enabling API TRO emission."
            ) from exc
        raise


def _call_simulation_tro_builder(
    builder: Callable[..., Mapping[str, Any]],
    kwargs: Mapping[str, Any],
    *,
    allow_degraded_builder: bool,
) -> tuple[Mapping[str, Any], tuple[str, ...]]:
    supported_fields = _supported_keyword_fields(builder, kwargs)
    omitted = tuple(
        sorted(
            key
            for key, value in kwargs.items()
            if value is not None and key not in supported_fields
        )
    )
    missing_run_binding = tuple(
        key
        for key in _RUN_BINDING_FIELDS
        if kwargs.get(key) is not None and key not in supported_fields
    )
    if missing_run_binding and not allow_degraded_builder:
        missing = ", ".join(missing_run_binding)
        raise TraceEmissionUnavailable(
            "Installed policyengine.provenance.trace.build_simulation_trace_tro "
            f"does not support API run binding fields: {missing}. Upgrade "
            "policyengine.py before enabling API TRO emission."
        )

    filtered_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key in supported_fields and value is not None
    }
    return builder(**filtered_kwargs), omitted


def _supported_keyword_fields(
    builder: Callable[..., Mapping[str, Any]],
    candidate_kwargs: Mapping[str, Any],
) -> set[str]:
    parameters = inspect.signature(builder).parameters.values()
    if any(parameter.kind == parameter.VAR_KEYWORD for parameter in parameters):
        return set(candidate_kwargs)
    return {
        parameter.name
        for parameter in inspect.signature(builder).parameters.values()
        if parameter.kind in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY)
    }


def _callable_supports(builder: Callable[..., Any], field: str) -> bool:
    parameters = inspect.signature(builder).parameters.values()
    return any(parameter.kind == parameter.VAR_KEYWORD for parameter in parameters) or (
        field in inspect.signature(builder).parameters
    )


def _drop_none(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    return {str(key): value for key, value in payload.items() if value is not None}
