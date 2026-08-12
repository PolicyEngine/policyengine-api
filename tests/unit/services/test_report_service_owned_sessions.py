import inspect
from pathlib import Path

import pytest
from sqlalchemy import func, select

from policyengine_api.data.v1_models import ReportOutput, ReportOutputRun
from policyengine_api.services.report_output_service import (
    ReportCreateResult,
    ReportOutputService,
    ReportOutputView,
)
from policyengine_api.services.simulation_service import SimulationService


ROUTE_PATH = (
    Path(__file__).parents[3]
    / "policyengine_api"
    / "routes"
    / "report_output_routes.py"
)


@pytest.fixture
def simulation_id(orm_session_factory):
    return (
        SimulationService(orm_session_factory)
        .get_or_create_simulation("us", "household-1", "household", 1)
        .simulation.id
    )


@pytest.fixture
def service(orm_session_factory):
    return ReportOutputService(orm_session_factory)


def test_report_public_methods_do_not_accept_sessions():
    for method_name in (
        "create_or_reuse_report_output",
        "resolve_report_output",
        "update_report_output",
    ):
        parameters = inspect.signature(
            getattr(ReportOutputService, method_name)
        ).parameters
        assert "session" not in parameters
        assert "session_factory" not in parameters


def test_report_routes_do_not_manage_sessions_or_query_run_services():
    source = ROUTE_PATH.read_text(encoding="utf-8")
    assert "get_v1_session_factory" not in source
    assert "report_run_service" not in source
    assert "sqlalchemy" not in source


def test_create_or_reuse_returns_report_and_display_run(service, simulation_id):
    created = service.create_or_reuse_report_output("us", simulation_id, year="2025")
    reused = service.create_or_reuse_report_output("us", simulation_id, year="2025")

    assert isinstance(created, ReportCreateResult)
    assert created.created is True
    assert isinstance(created.view, ReportOutputView)
    assert isinstance(created.view.report_output, ReportOutput)
    assert isinstance(created.view.display_run, ReportOutputRun)
    assert created.view.response_id is None
    assert reused.created is False
    assert reused.view.report_output.id == created.view.report_output.id


def test_create_rolls_back_all_rows_when_dual_write_fails(
    service,
    simulation_id,
    orm_session_factory,
    monkeypatch,
):
    def fail_dual_write(*args, **kwargs):
        raise RuntimeError("report dual write failed")

    monkeypatch.setattr(
        service, "_ensure_report_output_dual_write_state", fail_dual_write
    )

    with pytest.raises(RuntimeError, match="report dual write failed"):
        service.create_or_reuse_report_output("us", simulation_id, year="2026")

    with orm_session_factory() as session:
        report_count = session.scalar(select(func.count()).select_from(ReportOutput))
        run_count = session.scalar(select(func.count()).select_from(ReportOutputRun))
    assert report_count == 0
    assert run_count == 0


def test_update_returns_view_from_the_same_atomic_operation(
    service,
    simulation_id,
):
    created = service.create_or_reuse_report_output("us", simulation_id)

    view = service.update_report_output(
        "us",
        created.view.report_output.id,
        status="complete",
        output={"result": 42},
    )

    assert isinstance(view, ReportOutputView)
    assert view.report_output.output == {"result": 42}
    assert view.display_run.status == "complete"
