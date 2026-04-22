from sqlalchemy.engine.row import Row

from policyengine_api.data import database


class ReportOutputAliasService:
    def _get_report_output_row(self, report_output_id: int) -> dict | None:
        row: Row | None = database.query(
            """
            SELECT id, country_id, report_identity_hash, report_identity_schema_version
            FROM report_outputs
            WHERE id = ?
            """,
            (report_output_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _validate_alias_identity_compatibility(
        self,
        legacy_report_output: dict,
        canonical_report_output: dict,
    ) -> None:
        if legacy_report_output["country_id"] != canonical_report_output["country_id"]:
            raise ValueError(
                "Legacy and canonical report outputs must describe the same report"
            )

        if (
            legacy_report_output["report_identity_hash"] is None
            or legacy_report_output["report_identity_schema_version"] is None
        ):
            raise ValueError(
                "Legacy report output must have canonical report identity before "
                "aliasing"
            )

        if (
            canonical_report_output["report_identity_hash"] is None
            or canonical_report_output["report_identity_schema_version"] is None
        ):
            raise ValueError(
                "Canonical report output must have canonical report identity before "
                "aliasing"
            )

        if (
            legacy_report_output["report_identity_hash"]
            != canonical_report_output["report_identity_hash"]
            or legacy_report_output["report_identity_schema_version"]
            != canonical_report_output["report_identity_schema_version"]
        ):
            raise ValueError(
                "Legacy and canonical report outputs must share canonical report "
                "identity"
            )

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
            canonical_report_output_id = alias["canonical_report_output_id"]
            if self._get_report_output_row(canonical_report_output_id) is None:
                raise ValueError(
                    "Alias points to missing canonical report output "
                    f"#{canonical_report_output_id}"
                )
            return canonical_report_output_id

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
        legacy_report_output = self._get_report_output_row(legacy_report_output_id)
        if legacy_report_output is None:
            raise ValueError(
                f"Legacy report output #{legacy_report_output_id} not found"
            )

        canonical_report_output = self._get_report_output_row(
            canonical_report_output_id
        )
        if canonical_report_output is None:
            raise ValueError(
                f"Canonical report output #{canonical_report_output_id} not found"
            )
        if legacy_report_output_id == canonical_report_output_id:
            raise ValueError("Legacy and canonical report outputs must be different")

        existing_alias = self.get_alias(legacy_report_output_id)
        if existing_alias is not None:
            if (
                existing_alias["canonical_report_output_id"]
                == canonical_report_output_id
            ):
                return True

            raise ValueError(
                "Legacy report output alias already points to canonical report output "
                f"#{existing_alias['canonical_report_output_id']}"
            )

        self._validate_alias_identity_compatibility(
            legacy_report_output,
            canonical_report_output,
        )
        database.query(
            """
            INSERT INTO legacy_report_output_aliases
            (legacy_report_output_id, canonical_report_output_id)
            VALUES (?, ?)
            """,
            (legacy_report_output_id, canonical_report_output_id),
        )
        return True
