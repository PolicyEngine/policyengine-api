from sqlalchemy.engine.row import Row

from policyengine_api.data import database


class ReportOutputIdMapService:
    def _get_report_output_row(
        self,
        report_output_id: int,
        *,
        queryer=None,
        country_id: str | None = None,
    ) -> dict | None:
        queryer = queryer or database
        query = """
            SELECT id, country_id, report_identity_hash,
                   report_identity_schema_version
            FROM report_outputs
            WHERE id = ?
        """
        params: list[int | str] = [report_output_id]
        if country_id is not None:
            query += " AND country_id = ?"
            params.append(country_id)

        row: Row | None = queryer.query(query, tuple(params)).fetchone()
        return dict(row) if row is not None else None

    def _get_report_output_run_row(
        self,
        report_output_run_id: str,
        *,
        canonical_report_output_id: int,
        queryer=None,
    ) -> dict | None:
        queryer = queryer or database
        row: Row | None = queryer.query(
            """
            SELECT id, report_output_id
            FROM report_output_runs
            WHERE id = ? AND report_output_id = ?
            """,
            (report_output_run_id, canonical_report_output_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def _validate_mapping_identity_compatibility(
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
                "mapping"
            )

        if (
            canonical_report_output["report_identity_hash"] is None
            or canonical_report_output["report_identity_schema_version"] is None
        ):
            raise ValueError(
                "Canonical report output must have canonical report identity before "
                "mapping"
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

    def get_mapping(
        self,
        legacy_report_output_id: int,
        *,
        queryer=None,
    ) -> dict | None:
        queryer = queryer or database
        row: Row | None = queryer.query(
            """
            SELECT * FROM legacy_report_output_id_map
            WHERE legacy_report_output_id = ?
            """,
            (legacy_report_output_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def resolve_report_output_id(
        self,
        requested_report_output_id: int,
        *,
        queryer=None,
        country_id: str | None = None,
    ) -> dict | None:
        queryer = queryer or database
        mapping = self.get_mapping(requested_report_output_id, queryer=queryer)
        if mapping is not None:
            canonical_report_output_id = mapping["canonical_report_output_id"]
            canonical_report_output = self._get_report_output_row(
                canonical_report_output_id,
                queryer=queryer,
            )
            if canonical_report_output is None:
                raise ValueError(
                    "Legacy ID mapping points to missing canonical report output "
                    f"#{canonical_report_output_id}"
                )
            if (
                country_id is not None
                and canonical_report_output["country_id"] != country_id
            ):
                return None
            display_report_output_run_id = mapping["display_report_output_run_id"]
            display_run = self._get_report_output_run_row(
                display_report_output_run_id,
                canonical_report_output_id=canonical_report_output_id,
                queryer=queryer,
            )
            if display_run is None:
                raise ValueError(
                    "Legacy ID mapping points to missing display report output run "
                    f"#{display_report_output_run_id} for canonical report output "
                    f"#{canonical_report_output_id}"
                )
            return {
                "requested_report_output_id": requested_report_output_id,
                "canonical_report_output_id": canonical_report_output_id,
                "display_report_output_run_id": display_report_output_run_id,
                "is_legacy_id": True,
            }

        requested_report_output = self._get_report_output_row(
            requested_report_output_id,
            queryer=queryer,
            country_id=country_id,
        )
        if requested_report_output is None:
            return None

        return {
            "requested_report_output_id": requested_report_output_id,
            "canonical_report_output_id": requested_report_output_id,
            "display_report_output_run_id": None,
            "is_legacy_id": False,
        }

    def resolve_canonical_report_output_id(
        self,
        requested_report_output_id: int,
        *,
        queryer=None,
        country_id: str | None = None,
    ) -> int | None:
        resolution = self.resolve_report_output_id(
            requested_report_output_id,
            queryer=queryer,
            country_id=country_id,
        )
        if resolution is None:
            return None
        return resolution["canonical_report_output_id"]

    def set_mapping(
        self,
        legacy_report_output_id: int,
        canonical_report_output_id: int,
        display_report_output_run_id: str,
    ) -> bool:
        if legacy_report_output_id == canonical_report_output_id:
            raise ValueError("Legacy and canonical report outputs must be different")

        canonical_report_output = self._get_report_output_row(
            canonical_report_output_id
        )
        if canonical_report_output is None:
            raise ValueError(
                f"Canonical report output #{canonical_report_output_id} not found"
            )

        existing_mapping = self.get_mapping(legacy_report_output_id)
        if existing_mapping is not None:
            if (
                existing_mapping["canonical_report_output_id"]
                == canonical_report_output_id
                and existing_mapping["display_report_output_run_id"]
                == display_report_output_run_id
            ):
                return True

            raise ValueError(
                "Legacy report output ID already maps to canonical report output "
                f"#{existing_mapping['canonical_report_output_id']} and display "
                f"run #{existing_mapping['display_report_output_run_id']}"
            )

        legacy_report_output = self._get_report_output_row(legacy_report_output_id)
        if legacy_report_output is not None:
            self._validate_mapping_identity_compatibility(
                legacy_report_output,
                canonical_report_output,
            )

        display_run = self._get_report_output_run_row(
            display_report_output_run_id,
            canonical_report_output_id=canonical_report_output_id,
        )
        if display_run is None:
            raise ValueError(
                "Display report output run "
                f"#{display_report_output_run_id} not found for canonical report "
                f"#{canonical_report_output_id}"
            )

        database.query(
            """
            INSERT INTO legacy_report_output_id_map
            (
                legacy_report_output_id,
                canonical_report_output_id,
                display_report_output_run_id
            )
            VALUES (?, ?, ?)
            """,
            (
                legacy_report_output_id,
                canonical_report_output_id,
                display_report_output_run_id,
            ),
        )
        return True
