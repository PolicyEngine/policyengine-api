"""Public result and error types for v2 catalog publication."""

from __future__ import annotations

from dataclasses import dataclass


class CatalogPublicationError(RuntimeError):
    """Raised when publication cannot prove an atomic, complete result."""


@dataclass(frozen=True, slots=True)
class PrunedCatalogVersion:
    """A stored catalog version that pruning removed current-law data from.

    The counts are the rows deleted from each table: the version's current-law
    parameter values (those no policy or dynamic owns), its parameter tree
    rows and its parameter search files.
    """

    country_id: str
    policyengine_version: str
    parameter_values: int
    parameter_tree_children: int
    parameter_search_files: int


@dataclass(frozen=True, slots=True)
class CatalogPruningFailure:
    """A stored catalog version whose pruning failed and was rolled back.

    ``policyengine_version`` is None when reading the stored versions failed,
    before any version was chosen. ``error_type`` is the exception's class
    name; ``message`` names the country, the version if there is one and the
    database's error class and SQLSTATE, never a statement or row data.
    """

    country_id: str
    policyengine_version: str | None
    error_type: str
    message: str


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
    # Stored catalog versions whose time periods (metadata_time_periods)
    # publication replaced with the staged ones: country, version, and the
    # previous and new years, each in the order stored.
    time_period_updates: tuple[
        tuple[str, str, tuple[int, ...], tuple[int, ...]], ...
    ] = ()
    # The catalog's versions whose parameter tree this publication wrote:
    # model, version and tree rows. Empty when none needed one: each already
    # has its tree, or was stored before catalog format 2 and gets none.
    parameter_trees_written: tuple[tuple[str, str, int], ...] = ()
    # Published catalog versions whose parameter search file publication wrote:
    # model, version, and the file's uncompressed and compressed sizes in bytes.
    parameter_search_files_written: tuple[tuple[str, str, int, int], ...] = ()
    # Pruned catalog versions this publication published again, which it
    # restored: country, version and the current-law values written back. The
    # same publication writes their trees and search files, which the two
    # fields above list.
    restored_catalog_versions: tuple[tuple[str, str, int], ...] = ()
    # Older catalog versions pruned after the publication committed, and those
    # whose pruning failed and was rolled back; the next publication retries.
    pruned_catalog_versions: tuple[PrunedCatalogVersion, ...] = ()
    catalog_pruning_failures: tuple[CatalogPruningFailure, ...] = ()

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
            "updated_time_periods": [
                {
                    "country_id": country_id,
                    "policyengine_version": version,
                    "previous_time_periods": list(previous),
                    "time_periods": list(current),
                }
                for country_id, version, previous, current in self.time_period_updates
            ],
            "parameter_trees_written": [
                {"model": model_name, "version": version, "rows": rows}
                for model_name, version, rows in self.parameter_trees_written
            ],
            "parameter_search_files_written": [
                {
                    "model": model_name,
                    "version": version,
                    "uncompressed_bytes": uncompressed,
                    "compressed_bytes": compressed,
                }
                for model_name, version, uncompressed, compressed in (
                    self.parameter_search_files_written
                )
            ],
            "restored_catalog_versions": [
                {
                    "country_id": country_id,
                    "policyengine_version": version,
                    "parameter_values": parameter_values,
                }
                for country_id, version, parameter_values in (
                    self.restored_catalog_versions
                )
            ],
            "pruned_catalog_versions": [
                {
                    "country_id": pruned.country_id,
                    "policyengine_version": pruned.policyengine_version,
                    "deleted_rows": {
                        "parameter_values": pruned.parameter_values,
                        "parameter_tree_children": pruned.parameter_tree_children,
                        "parameter_search_files": pruned.parameter_search_files,
                    },
                }
                for pruned in self.pruned_catalog_versions
            ],
            "catalog_pruning_failures": [
                {
                    "country_id": failure.country_id,
                    "policyengine_version": failure.policyengine_version,
                    "error_type": failure.error_type,
                    "message": failure.message,
                }
                for failure in self.catalog_pruning_failures
            ],
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }
