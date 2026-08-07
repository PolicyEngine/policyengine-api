from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import ReportDAO, V1UnitOfWork


class ReportOutputAliasService:
    def __init__(
        self,
        reports: ReportDAO | None = None,
        *,
        unit_of_work: V1UnitOfWork | None = None,
    ):
        self._reports = reports
        self._unit_of_work = unit_of_work

    @property
    def unit_of_work(self) -> V1UnitOfWork:
        if self._unit_of_work is None:
            self._unit_of_work = V1UnitOfWork(build_v1_session_manager())
        return self._unit_of_work

    def _get_report_output_row(self, report_output_id: int) -> dict | None:
        if self._reports is not None:
            return self._reports.get(report_output_id)
        with self.unit_of_work.read() as daos:
            return daos.reports.get(report_output_id)

    def get_alias(self, legacy_report_output_id: int) -> dict | None:
        if self._reports is not None:
            return self._reports.get_alias(legacy_report_output_id)
        with self.unit_of_work.read() as daos:
            return daos.reports.get_alias(legacy_report_output_id)

    def resolve_canonical_report_output_id(
        self, requested_report_output_id: int
    ) -> int | None:
        if self._reports is not None:
            return self._resolve(self._reports, requested_report_output_id)
        with self.unit_of_work.read() as daos:
            return self._resolve(daos.reports, requested_report_output_id)

    def _resolve(
        self, reports: ReportDAO, requested_report_output_id: int
    ) -> int | None:
        alias = reports.get_alias(requested_report_output_id)
        if alias is not None:
            canonical_id = alias["canonical_report_output_id"]
            if reports.get(canonical_id) is None:
                raise ValueError(
                    f"Alias points to missing canonical report output #{canonical_id}"
                )
            return canonical_id
        row = reports.get(requested_report_output_id)
        return row["id"] if row is not None else None

    def set_alias(
        self, legacy_report_output_id: int, canonical_report_output_id: int
    ) -> bool:
        if self._reports is not None:
            return self._set_alias(
                self._reports,
                legacy_report_output_id,
                canonical_report_output_id,
            )
        with self.unit_of_work.transaction() as daos:
            return self._set_alias(
                daos.reports,
                legacy_report_output_id,
                canonical_report_output_id,
            )

    def _set_alias(
        self,
        reports: ReportDAO,
        legacy_report_output_id: int,
        canonical_report_output_id: int,
    ) -> bool:
        legacy = reports.get(legacy_report_output_id)
        if legacy is None:
            raise ValueError(
                f"Legacy report output #{legacy_report_output_id} not found"
            )
        canonical = reports.get(canonical_report_output_id)
        if canonical is None:
            raise ValueError(
                f"Canonical report output #{canonical_report_output_id} not found"
            )
        if legacy_report_output_id == canonical_report_output_id:
            raise ValueError("Legacy and canonical report outputs must be different")
        existing = reports.get_alias(legacy_report_output_id)
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
        reports.set_alias(legacy_report_output_id, canonical_report_output_id)
        return True
