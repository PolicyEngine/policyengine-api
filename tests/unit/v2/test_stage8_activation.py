"""Guards that keep the dormant v2 report schema off production paths."""

import inspect

from policyengine_api.migration_flags import (
    DEFAULT_DB_SOURCE,
    DEFAULT_SIM_COMPUTE_BACKEND,
    DEFAULT_SIM_ENTRYPOINT,
    RouteImplementation,
    get_migration_context,
)
from policyengine_api.routes import report_output_routes
from policyengine_api.services.report_output_service import ReportOutputService


def test_default_report_migration_context_keeps_existing_owners(
    monkeypatch,
) -> None:
    for name in (
        "DB_READ_REPORT",
        "DB_WRITE_REPORT",
        "ROUTE_IMPL_REPORT",
        "SIM_COMPUTE_REPORT",
        "SIM_ENTRYPOINT",
    ):
        monkeypatch.delenv(name, raising=False)

    context = get_migration_context("report")

    assert DEFAULT_DB_SOURCE == "cloud_sql"
    assert context.db_read == "cloud_sql"
    assert context.db_write == "cloud_sql"
    assert context.route_impl is RouteImplementation.FLASK_FALLBACK
    assert context.sim_compute == DEFAULT_SIM_COMPUTE_BACKEND == "old_gateway"
    assert context.sim_entrypoint == DEFAULT_SIM_ENTRYPOINT == "old_gateway_direct"


def test_existing_report_route_and_service_import_only_v1_persistence() -> None:
    route_source = inspect.getsource(report_output_routes)
    service_source = inspect.getsource(ReportOutputService)

    assert "policyengine_api.data.v2" not in route_source
    assert "policyengine_api.data.v2" not in service_source
    assert "get_v1_session_factory" in service_source
    assert "ReportOutput" in service_source
    assert "ReportOutputRun" in service_source
