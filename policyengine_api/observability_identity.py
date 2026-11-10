"""The service and deployment identity on every record the Public API writes.

The API's runtime (``policyengine_api.observability``) and gunicorn's main
process (``policyengine_api.gunicorn_worker_exits``) both build their
observability configuration from these functions, so the daily telemetry
error report selects and groups their records alike. This module builds no
runtime when imported, unlike ``policyengine_api.observability``, so gunicorn's
main process can import it before it forks the workers.
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

from policyengine_observability import (
    DeploymentIdentity,
    GoogleCloudLogFormatter,
    ServiceIdentity,
    StdoutLogDestination,
    process_instance_id,
)

SERVICE_NAME = "policyengine-api"
DEFAULT_SERVICE_NAMESPACE = "policyengine.api-v1"


def package_version() -> str:
    """Return the installed policyengine-api version."""
    try:
        return version("policyengine-api")
    except PackageNotFoundError:
        return "4.1.0"


def service_identity() -> ServiceIdentity:
    """Return the service identity, with the namespace the deployment sets."""
    return ServiceIdentity(
        name=SERVICE_NAME,
        namespace=os.getenv(
            "OBSERVABILITY_SERVICE_NAMESPACE",
            DEFAULT_SERVICE_NAMESPACE,
        ),
        version=package_version(),
        role="api",
    )


def deployment_identity() -> DeploymentIdentity:
    """Return the deployment identity of the calling process.

    The instance ID includes the process ID, so call this in the process that
    writes the records, after any fork.
    """
    environment = os.getenv("APP_ENVIRONMENT", "local").strip() or "local"
    return DeploymentIdentity(
        environment=environment,
        platform="google_cloud_run",
        region=os.getenv("CLOUD_RUN_REGION") or "us-central1",
        instance_id=process_instance_id(SERVICE_NAME, os.getenv("K_REVISION")),
    )


def standard_output_destination() -> StdoutLogDestination:
    """Return the standard-output destination Cloud Run's log sinks read.

    With a trace project set, records use Google Cloud's structured-logging
    fields, so Cloud Logging reads their severity and trace.
    """
    trace_project = os.getenv("OBSERVABILITY_TRACE_PROJECT_ID", "").strip()
    formatter = GoogleCloudLogFormatter(trace_project) if trace_project else None
    return StdoutLogDestination(formatter=formatter)
