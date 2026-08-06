from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import ReportDAO


class ReportOutputAliasService:
    def __init__(self, reports: ReportDAO | None = None):
        self._reports = reports

    @property
    def reports(self) -> ReportDAO:
        if self._reports is None:
            self._reports = ReportDAO(build_v1_session_manager())
        return self._reports

    def _get_report_output_row(self, report_output_id: int) -> dict | None:
        return self.reports.get(report_output_id)

    def get_alias(self, legacy_report_output_id: int) -> dict | None:
        return self.reports.get_alias(legacy_report_output_id)

    def resolve_canonical_report_output_id(
        self, requested_report_output_id: int
    ) -> int | None:
        alias = self.get_alias(requested_report_output_id)
        if alias is not None:
            canonical_id = alias["canonical_report_output_id"]
            if self.reports.get(canonical_id) is None:
                raise ValueError(
                    f"Alias points to missing canonical report output #{canonical_id}"
                )
            return canonical_id
        row = self.reports.get(requested_report_output_id)
        return row["id"] if row is not None else None

    def set_alias(
        self, legacy_report_output_id: int, canonical_report_output_id: int
    ) -> bool:
        legacy = self.reports.get(legacy_report_output_id)
        if legacy is None:
            raise ValueError(
                f"Legacy report output #{legacy_report_output_id} not found"
            )
        canonical = self.reports.get(canonical_report_output_id)
        if canonical is None:
            raise ValueError(
                f"Canonical report output #{canonical_report_output_id} not found"
            )
        if legacy_report_output_id == canonical_report_output_id:
            raise ValueError("Legacy and canonical report outputs must be different")
        existing = self.reports.get_alias(legacy_report_output_id)
        if existing is not None:
            if existing["canonical_report_output_id"] == canonical_report_output_id:
                return True
            raise ValueError(
                "Legacy report output alias already points to canonical report output "
                f"#{existing['canonical_report_output_id']}"
            )
        logical_key = ("country_id", "simulation_1_id", "simulation_2_id", "year")
        if any(legacy[field] != canonical[field] for field in logical_key):
            raise ValueError(
                "Legacy and canonical report outputs must describe the same report"
            )
        self.reports.set_alias(legacy_report_output_id, canonical_report_output_id)
        return True
