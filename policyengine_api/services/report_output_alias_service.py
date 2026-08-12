from sqlalchemy.orm import Session

from policyengine_api.data.v1_models import LegacyReportOutputAlias, ReportOutput


class ReportOutputAliasService:
    """Legacy report-ID aliases persisted through mapped ORM models."""

    @staticmethod
    def get_alias(
        session: Session, legacy_report_output_id: int
    ) -> LegacyReportOutputAlias | None:
        return session.get(LegacyReportOutputAlias, legacy_report_output_id)

    def resolve_canonical_report_output_id(
        self, session: Session, requested_report_output_id: int
    ) -> int | None:
        alias = self.get_alias(session, requested_report_output_id)
        if alias is not None:
            canonical_id = alias.canonical_report_output_id
            if session.get(ReportOutput, canonical_id) is None:
                raise ValueError(
                    f"Alias points to missing canonical report output #{canonical_id}"
                )
            return canonical_id
        report = session.get(ReportOutput, requested_report_output_id)
        return report.id if report is not None else None

    def set_alias(
        self,
        session: Session,
        legacy_report_output_id: int,
        canonical_report_output_id: int,
    ) -> bool:
        legacy = session.get(ReportOutput, legacy_report_output_id)
        if legacy is None:
            raise ValueError(
                f"Legacy report output #{legacy_report_output_id} not found"
            )
        canonical = session.get(ReportOutput, canonical_report_output_id)
        if canonical is None:
            raise ValueError(
                f"Canonical report output #{canonical_report_output_id} not found"
            )
        if legacy_report_output_id == canonical_report_output_id:
            raise ValueError("Legacy and canonical report outputs must be different")
        existing = self.get_alias(session, legacy_report_output_id)
        if existing is not None:
            if existing.canonical_report_output_id == canonical_report_output_id:
                return True
            raise ValueError(
                "Legacy report output alias already points to canonical report output "
                f"#{existing.canonical_report_output_id}"
            )
        logical_fields = (
            "country_id",
            "simulation_1_id",
            "simulation_2_id",
            "year",
        )
        if any(
            getattr(legacy, field) != getattr(canonical, field)
            for field in logical_fields
        ):
            raise ValueError(
                "Legacy and canonical report outputs must describe the same report"
            )
        session.add(
            LegacyReportOutputAlias(
                legacy_report_output_id=legacy_report_output_id,
                canonical_report_output_id=canonical_report_output_id,
            )
        )
        session.flush()
        return True
