from policyengine_api import constants
from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.data.v1_models import ReportOutput


def insert_outdated_report_output(
    orm_session_factory, monkeypatch, country_id: str, **fields
) -> int:
    """Save a report output under the previous report-output cache version.

    The cache version is computed with the ``report_output`` schema version set
    to 2, and the schema version is set back to 3 before the record is saved,
    so the record reads as outdated against the current cache version.
    ``fields`` are the record's other columns, e.g. its simulation IDs, year
    and output; its status is "complete" unless given.
    """
    monkeypatch.setitem(constants.RUNTIME_CACHE_SCHEMA_VERSIONS, "report_output", 2)
    outdated_cache_version = get_report_output_cache_version(country_id)
    monkeypatch.setitem(constants.RUNTIME_CACHE_SCHEMA_VERSIONS, "report_output", 3)
    assert outdated_cache_version != get_report_output_cache_version(country_id)
    with orm_session_factory.begin() as session:
        outdated = ReportOutput(
            country_id=country_id,
            api_version=outdated_cache_version,
            **{"status": "complete", **fields},
        )
        session.add(outdated)
        session.flush()
        return outdated.id
