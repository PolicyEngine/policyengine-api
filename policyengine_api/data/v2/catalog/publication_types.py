"""Public result and error types for v2 catalog publication."""

from __future__ import annotations

from dataclasses import dataclass


class CatalogPublicationError(RuntimeError):
    """Raised when publication cannot prove an atomic, complete result."""


@dataclass(frozen=True, slots=True)
class PublicationEvidence:
    """Non-secret facts emitted after a successful publication."""

    policyengine_version: str
    dependency_versions: tuple[tuple[str, str], ...]
    entity_counts: dict[str, int]
    fallback_summaries: tuple[tuple[str, str, int], ...]
    elapsed_seconds: float
    omitted_region_summaries: tuple[tuple[str, str, int], ...] = ()
    # Stored catalog versions whose region rows were kept although the staged
    # regions differ: country, version, stored and staged region counts.
    kept_region_summaries: tuple[tuple[str, str, int, int], ...] = ()
    # Stored catalog versions whose parameter tree publication wrote: model,
    # version and rows written. Empty once every stored version has its tree.
    parameter_trees_written: tuple[tuple[str, str, int], ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Return the evidence as the JSON object printed after a publication."""
        return {
            "outcome": "ok",
            "policyengine_version": self.policyengine_version,
            "dependency_versions": dict(self.dependency_versions),
            "entity_counts": self.entity_counts,
            "fallback_summaries": [
                {
                    "country_id": country_id,
                    "region_type": region_type,
                    "count": count,
                }
                for country_id, region_type, count in self.fallback_summaries
            ],
            "omitted_region_summaries": [
                {
                    "country_id": country_id,
                    "region_type": region_type,
                    "count": count,
                }
                for country_id, region_type, count in self.omitted_region_summaries
            ],
            "kept_regions": [
                {
                    "country_id": country_id,
                    "policyengine_version": version,
                    "stored_regions": stored,
                    "staged_regions": staged,
                }
                for country_id, version, stored, staged in self.kept_region_summaries
            ],
            "parameter_trees_written": [
                {"model": model_name, "version": version, "rows": rows}
                for model_name, version, rows in self.parameter_trees_written
            ],
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }
