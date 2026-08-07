import pytest

from policyengine_api.data.v1_models import ReportOutput, ReportOutputRun
from policyengine_api.services.report_run_service import ReportRunService


service = ReportRunService()


def create_report(orm_session, *, status="pending"):
    report = ReportOutput(
        country_id="us",
        simulation_1_id=1,
        simulation_2_id=None,
        api_version="1",
        status=status,
        year="2025",
    )
    orm_session.add(report)
    orm_session.flush()
    return report


def test_creates_mapped_runs_with_incrementing_sequence_and_python_json(orm_session):
    report = create_report(orm_session)

    first = service.create_report_output_run(
        orm_session,
        report.id,
        trigger_type="initial",
        report_spec_snapshot={"country_id": "us"},
        version_manifest={"report_cache_version": "r123"},
    )
    second = service.create_report_output_run(
        orm_session, report.id, trigger_type="rerun"
    )

    assert isinstance(first, ReportOutputRun)
    assert first.run_sequence == 1
    assert first.requested_at is not None
    assert first.started_at is None
    assert first.finished_at is None
    assert first.report_spec_snapshot_json == {"country_id": "us"}
    assert first.report_cache_version == "r123"
    assert second.run_sequence == 2


@pytest.mark.parametrize(
    ("status", "has_started", "has_finished"),
    [
        ("pending", False, False),
        ("running", True, False),
        ("complete", True, True),
        ("error", True, True),
    ],
)
def test_sets_run_timestamps_from_status(
    orm_session, status, has_started, has_finished
):
    report = create_report(orm_session)

    run = service.create_report_output_run(orm_session, report.id, status=status)

    assert (run.started_at is not None) is has_started
    assert (run.finished_at is not None) is has_finished


def test_raises_when_parent_report_is_missing(orm_session):
    with pytest.raises(ValueError, match="Report output #999 not found"):
        service.create_report_output_run(orm_session, 999)


def test_gets_lists_and_selects_mapped_runs(orm_session):
    report = create_report(orm_session)
    first = service.create_report_output_run(orm_session, report.id, status="complete")
    second = service.create_report_output_run(orm_session, report.id, status="running")
    report.latest_successful_run_id = first.id
    report.active_run_id = second.id

    assert service.get_report_output_run(orm_session, first.id) is first
    assert service.list_report_output_runs(orm_session, report.id) == [first, second]
    assert service.get_newest_report_output_run(orm_session, report.id) is second
    assert service.select_display_run(orm_session, report) is second


def test_select_display_run_falls_back_to_matching_error(orm_session):
    report = create_report(orm_session, status="error")
    matching = service.create_report_output_run(
        orm_session,
        report.id,
        status="error",
        error_message="failed",
    )
    service.create_report_output_run(orm_session, report.id)
    report.error_message = "failed"
    report.active_run_id = None

    assert service.select_display_run(orm_session, report) is matching
