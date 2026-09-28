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


DISPATCH_ATTRIBUTE_KEYS = frozenset({"observability_id"})


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
        dispatch_attribute_keys=DISPATCH_ATTRIBUTE_KEYS,
    )
    config = replace(
        config,
        otel=replace(config.otel, sampling_ratio=1.0),
    )
    return configure(config)


runtime = _build_runtime()


def get_runtime() -> ObservabilityRuntime:
    return runtime
