"""Explicit API v1 observability runtime ownership."""

from __future__ import annotations

import os
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version

from policyengine_observability import (
    DeploymentIdentity,
    GoogleCloudLogFormatter,
    LoggingConfig,
    ObservabilityConfig,
    ObservabilityRuntime,
    ServiceIdentity,
    StdoutLogDestination,
    configure,
)


APPLICATION_ATTRIBUTE_KEYS = frozenset(
    {
        "backend",
        "configured_write_source",
        "baseline_policy_id",
        "batch_job_id",
        "cache_backend",
        "cache_event",
        "country_id",
        "data_version",
        "db_entity",
        "db_read",
        "db_read_source",
        "db_write",
        "db_write_source",
        "elapsed_ms",
        "error_code",
        "error_type",
        "execution_id",
        "failure_category",
        "http_status",
        "job_id",
        "latency_ms",
        "max_parallel",
        "method",
        "metric_name",
        "metric_value",
        "migration_flag_error",
        "model_version",
        "path",
        "policy_id",
        "policyengine_version",
        "submission_claim_id",
        "requested_through_revision",
        "resource",
        "request_id",
        "observability_id",
        "resolved_app_name",
        "route_group",
        "route_impl",
        "simulation_year",
        "sim_compute",
        "sim_entrypoint",
        "sim_flow",
        "source_revision",
        "start_year",
        "status",
        "status_code",
        "window_size",
    }
)


def _package_version() -> str:
    try:
        return version("policyengine-api")
    except PackageNotFoundError:
        return "4.1.0"


def _build_runtime() -> ObservabilityRuntime:
    environment = os.getenv("APP_ENVIRONMENT", "local").strip() or "local"
    trace_project = os.getenv("OBSERVABILITY_TRACE_PROJECT_ID", "").strip()
    formatter = GoogleCloudLogFormatter(trace_project) if trace_project else None
    config = ObservabilityConfig.from_env(
        service=ServiceIdentity(
            name="policyengine-api",
            namespace=os.getenv(
                "OBSERVABILITY_SERVICE_NAMESPACE",
                "policyengine.api-v1",
            ),
            version=_package_version(),
            role="api",
        ),
        deployment=DeploymentIdentity(
            environment=environment,
            platform="google_cloud_run",
            region=os.getenv("CLOUD_RUN_REGION") or "us-central1",
            instance_id=os.getenv("K_REVISION"),
        ),
        logging=LoggingConfig(
            destinations=(StdoutLogDestination(formatter=formatter),),
            capture_standard_library=True,
        ),
        application_attribute_keys=APPLICATION_ATTRIBUTE_KEYS,
    )
    config = replace(
        config,
        otel=replace(config.otel, sampling_ratio=1.0),
    )
    return configure(config)


runtime = _build_runtime()


def get_runtime() -> ObservabilityRuntime:
    return runtime
