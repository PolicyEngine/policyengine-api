"""Aliases that redirect a legacy v1 report output ID to its canonical report output."""

from sqlalchemy.orm import Session

from policyengine_api.data.v1_models import LegacyReportOutputAlias, ReportOutput


class ReportOutputAliasService:
    """Legacy report-ID aliases persisted through mapped ORM models."""

    @staticmethod
    def get_alias(
        session: Session, legacy_report_output_id: int
    ) -> LegacyReportOutputAlias | None:
        """Return the alias stored for this legacy report output ID, or None."""
        return session.get(LegacyReportOutputAlias, legacy_report_output_id)

    def resolve_canonical_report_output_id(
        self, session: Session, requested_report_output_id: int
    ) -> int | None:
        """Return the report output ID to serve for a requested ID, following any alias.

        Return None if there is neither an alias nor a report output with this ID, and
        raise ValueError if the alias points to a missing report output.
        """
        alias = self.get_alias(session, requested_report_output_id)
        if alias is not None:
            canonical_id = alias.canonical_report_output_id
            if session.get(ReportOutput, canonical_id) is None:
                msg = f"Alias points to missing canonical report output #{canonical_id}"
                raise ValueError(msg)
            return canonical_id
        report = session.get(ReportOutput, requested_report_output_id)
        return report.id if report is not None else None

    def set_alias(
        self,
        session: Session,
        legacy_report_output_id: int,
        canonical_report_output_id: int,
    ) -> bool:
        """Point a legacy report output at a canonical one describing the same report.

        Repeating an existing alias is a no-op; the caller owns the transaction. Raise
        ValueError if either output is missing, both IDs are the same, the legacy output
        is already aliased elsewhere, or the two differ in country, simulations or year.
        Always return True.
        """
        legacy = session.get(ReportOutput, legacy_report_output_id)
        if legacy is None:
            msg = f"Legacy report output #{legacy_report_output_id} not found"
            raise ValueError(msg)
        canonical = session.get(ReportOutput, canonical_report_output_id)
        if canonical is None:
            msg = f"Canonical report output #{canonical_report_output_id} not found"
            raise ValueError(msg)
        if legacy_report_output_id == canonical_report_output_id:
            msg = "Legacy and canonical report outputs must be different"
            raise ValueError(msg)
        existing = self.get_alias(session, legacy_report_output_id)
        if existing is not None:
            if existing.canonical_report_output_id == canonical_report_output_id:
                return True
            msg = (
                "Legacy report output alias already points to canonical report output "
                f"#{existing.canonical_report_output_id}"
            )
            raise ValueError(msg)
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
            msg = "Legacy and canonical report outputs must describe the same report"
            raise ValueError(msg)
        session.add(
            LegacyReportOutputAlias(
                legacy_report_output_id=legacy_report_output_id,
                canonical_report_output_id=canonical_report_output_id,
            )
        )
        session.flush()
        return True
