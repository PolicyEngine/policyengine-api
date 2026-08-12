import pytest

from policyengine_api.data.v1_models import (
    LegacyReportOutputAlias,
    ReportOutput,
)
from policyengine_api.services.report_output_alias_service import (
    ReportOutputAliasService,
)


service = ReportOutputAliasService()


def add_report(orm_session, report_id):
    report = ReportOutput(
        id=report_id,
        country_id="us",
        simulation_1_id=1,
        simulation_2_id=None,
        api_version="1",
        status="pending",
        year="2025",
    )
    orm_session.add(report)
    orm_session.flush()
    return report


def test_sets_and_resolves_mapped_alias(orm_session):
    add_report(orm_session, 100)
    add_report(orm_session, 200)

    assert service.set_alias(orm_session, 100, 200) is True

    alias = service.get_alias(orm_session, 100)
    assert isinstance(alias, LegacyReportOutputAlias)
    assert alias.canonical_report_output_id == 200
    assert service.resolve_canonical_report_output_id(orm_session, 100) == 200
    assert service.resolve_canonical_report_output_id(orm_session, 200) == 200


def test_setting_same_alias_is_idempotent(orm_session):
    add_report(orm_session, 100)
    add_report(orm_session, 200)

    service.set_alias(orm_session, 100, 200)

    assert service.set_alias(orm_session, 100, 200) is True


def test_rejects_conflicting_alias(orm_session):
    add_report(orm_session, 100)
    add_report(orm_session, 200)
    add_report(orm_session, 300)
    service.set_alias(orm_session, 100, 200)

    with pytest.raises(ValueError, match="already points"):
        service.set_alias(orm_session, 100, 300)


def test_rejects_missing_and_self_aliases(orm_session):
    add_report(orm_session, 100)

    with pytest.raises(ValueError, match="Canonical report output #999 not found"):
        service.set_alias(orm_session, 100, 999)
    with pytest.raises(ValueError, match="must be different"):
        service.set_alias(orm_session, 100, 100)


def test_rejects_reports_with_different_logical_keys(orm_session):
    add_report(orm_session, 100)
    different = add_report(orm_session, 200)
    different.year = "2026"

    with pytest.raises(ValueError, match="must describe the same report"):
        service.set_alias(orm_session, 100, 200)


def test_rejects_alias_pointing_to_missing_canonical_report(orm_session):
    add_report(orm_session, 100)
    orm_session.add(
        LegacyReportOutputAlias(
            legacy_report_output_id=100,
            canonical_report_output_id=999,
        )
    )
    orm_session.flush()

    with pytest.raises(ValueError, match="missing canonical report output #999"):
        service.resolve_canonical_report_output_id(orm_session, 100)
