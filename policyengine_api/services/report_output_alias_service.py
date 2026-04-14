from sqlalchemy.engine.row import Row

from policyengine_api.data import database


class ReportOutputAliasService:
    def get_alias(self, legacy_report_output_id: int) -> dict | None:
        row: Row | None = database.query(
            """
            SELECT * FROM legacy_report_output_aliases
            WHERE legacy_report_output_id = ?
            """,
            (legacy_report_output_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def resolve_canonical_report_output_id(
        self, requested_report_output_id: int
    ) -> int | None:
        alias = self.get_alias(requested_report_output_id)
        if alias is not None:
            return alias["canonical_report_output_id"]

        row: Row | None = database.query(
            "SELECT id FROM report_outputs WHERE id = ?",
            (requested_report_output_id,),
        ).fetchone()
        return row["id"] if row is not None else None

    def set_alias(
        self,
        legacy_report_output_id: int,
        canonical_report_output_id: int,
    ) -> bool:
        existing_alias = self.get_alias(legacy_report_output_id)
        if existing_alias is None:
            database.query(
                """
                INSERT INTO legacy_report_output_aliases
                (legacy_report_output_id, canonical_report_output_id)
                VALUES (?, ?)
                """,
                (legacy_report_output_id, canonical_report_output_id),
            )
            return True

        database.query(
            """
            UPDATE legacy_report_output_aliases
            SET canonical_report_output_id = ?
            WHERE legacy_report_output_id = ?
            """,
            (canonical_report_output_id, legacy_report_output_id),
        )
        return True
