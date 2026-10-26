"""Give each reference region its dataset and filter from the certified data release.

A scoping rule per country and region type names the release's dataset role
(a key of the release manifest's ``region_datasets``) and the household column
whose value selects the region's households in that dataset. Region types
without a rule cannot run yet, so publication leaves them out and counts them.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from policyengine_api.data.v2.catalog.errors import CatalogExtractionError
from policyengine_api.data.v2.catalog.records import CertifiedArtifact

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.region_references import RegionReference

ROW_FILTER = "row_filter"
NATIONAL_DATASET_ROLE = "national"


@dataclass(frozen=True, slots=True)
class RegionScopingRule:
    """How regions of one type find their dataset and select their households.

    ``filter_field`` is the household column a row filter compares with the
    region's filter value. When the release names no dataset for the role,
    the regions use the default dataset, unless ``requires_release_dataset``:
    then only the routed dataset carries the column, and scoping fails.
    """

    dataset_role: str
    filter_strategy: str | None = None
    filter_field: str | None = None
    requires_release_dataset: bool = False


REGION_SCOPING_RULES: Mapping[tuple[str, str], RegionScopingRule] = {
    ("us", "national"): RegionScopingRule(NATIONAL_DATASET_ROLE),
    ("us", "state"): RegionScopingRule("state", ROW_FILTER, "state_fips"),
    ("us", "congressional_district"): RegionScopingRule(
        "congressional_district", ROW_FILTER, "congressional_district_geoid"
    ),
    ("uk", "national"): RegionScopingRule(NATIONAL_DATASET_ROLE),
    ("uk", "country"): RegionScopingRule(NATIONAL_DATASET_ROLE, ROW_FILTER, "region"),
    # The UK national file has no area codes; the release routes constituencies
    # and local authorities to a local-area dataset that carries them.
    ("uk", "constituency"): RegionScopingRule(
        "constituency",
        ROW_FILTER,
        "constituency_code_oa",
        requires_release_dataset=True,
    ),
    ("uk", "local_authority"): RegionScopingRule(
        "local_authority",
        ROW_FILTER,
        "la_code_oa",
        requires_release_dataset=True,
    ),
}


@dataclass(frozen=True, slots=True)
class ScopedRegion:
    """A reference region with its dataset and the filter selecting its households."""

    reference: RegionReference
    dataset_name: str
    filter_strategy: str | None
    filter_field: str | None


@dataclass(frozen=True, slots=True)
class RegionScoping:
    """Every runnable region of one country, and what the others fell back to.

    ``fallback_counts`` counts, by region type, regions whose dataset role the
    release does not name, so they use the default dataset; ``omitted_counts``
    counts the regions left out because their type cannot run yet.
    """

    regions: tuple[ScopedRegion, ...]
    dataset_names: frozenset[str]
    certified_artifacts: Mapping[str, CertifiedArtifact]
    fallback_counts: Mapping[str, int]
    omitted_counts: Mapping[str, int]


def _manifest_text(value: object, *, description: str) -> str:
    if not isinstance(value, str) or not value:
        msg = f"{description} must be a non-empty string"
        raise CatalogExtractionError(msg)
    return value


@runtime_checkable
class ReleaseManifest(Protocol):
    """What scoping reads from a PolicyEngine.py country release manifest.

    The manifest is an untyped public object, so each value is checked where
    it is read.
    """

    @property
    def datasets(self) -> object:
        """The certified artifacts by name."""
        ...

    @property
    def region_datasets(self) -> object:
        """The dataset path of each region type."""
        ...

    @property
    def data_package(self) -> object:
        """The repository and revision artifacts default to."""
        ...


def certified_artifacts(
    country_id: str,
    release_manifest: ReleaseManifest,
) -> dict[str, CertifiedArtifact]:
    """Return the release manifest's artifacts, with the data package's defaults.

    An artifact without its own repository, repository type or revision is in
    the data package's repository at the release revision.
    """
    data_package = release_manifest.data_package
    default_repo_id = getattr(data_package, "repo_id", None)
    default_repo_type = getattr(data_package, "repo_type", None) or "model"
    default_revision = getattr(
        data_package, "release_manifest_revision", None
    ) or getattr(data_package, "version", None)
    datasets = release_manifest.datasets
    if not isinstance(datasets, Mapping):
        msg = f"{country_id} release manifest has no dataset map"
        raise CatalogExtractionError(msg)
    artifacts: dict[str, CertifiedArtifact] = {}
    for name, reference in datasets.items():
        description = f"{country_id} release artifact {name}"
        artifacts[name] = CertifiedArtifact(
            name=_manifest_text(name, description=f"{country_id} release artifact"),
            repo_id=_manifest_text(
                getattr(reference, "repo_id", None) or default_repo_id,
                description=f"{description} repository",
            ),
            repo_type=_manifest_text(
                getattr(reference, "repo_type", None) or default_repo_type,
                description=f"{description} repository type",
            ),
            path=_manifest_text(
                getattr(reference, "path", None), description=f"{description} path"
            ),
            revision=_manifest_text(
                getattr(reference, "revision", None) or default_revision,
                description=f"{description} revision",
            ),
            sha256=getattr(reference, "sha256", None),
        )
    return artifacts


def _role_datasets(
    country_id: str,
    release_manifest: ReleaseManifest,
    artifacts: Mapping[str, CertifiedArtifact],
) -> dict[str, str]:
    """Map each dataset role the release names to its certified dataset's name."""
    region_datasets = release_manifest.region_datasets
    if not isinstance(region_datasets, Mapping):
        msg = f"{country_id} release manifest has no region dataset map"
        raise CatalogExtractionError(msg)
    names_by_path = {artifact.path: name for name, artifact in artifacts.items()}
    role_datasets: dict[str, str] = {}
    for role, template in region_datasets.items():
        path = _manifest_text(
            getattr(template, "path_template", None),
            description=f"{country_id} {role} region dataset",
        )
        if "{" in path:
            msg = (
                f"{country_id} {role} regions name a per-region dataset template "
                f"{path!r}, which the catalog does not support"
            )
            raise CatalogExtractionError(msg)
        if path not in names_by_path:
            msg = (
                f"{country_id} release names no certified dataset at path {path!r} "
                f"for {role} regions"
            )
            raise CatalogExtractionError(msg)
        role_datasets[role] = names_by_path[path]
    return role_datasets


def _checked_filter_value(reference: RegionReference, rule: RegionScopingRule) -> None:
    """Require a filter value exactly when the rule filters, and valid list values."""
    value = reference.filter_value
    if rule.filter_strategy is None:
        if value is not None:
            msg = (
                f"region {reference.code!r} has a filter value, but a national region "
                "selects every household"
            )
            raise CatalogExtractionError(msg)
        return
    if value is None:
        msg = f"region {reference.code!r} has no filter value"
        raise CatalogExtractionError(msg)
    if value.startswith(("[", "{")):
        try:
            members = json.loads(value, parse_constant=_reject_constant)
        except ValueError:
            members = None
        if not (
            isinstance(members, list)
            and members
            and all(isinstance(member, (str, int, float, bool)) for member in members)
        ):
            msg = f"region {reference.code!r} has an unsupported filter value"
            raise CatalogExtractionError(msg)


def _reject_constant(constant: str) -> object:
    msg = f"{constant} is not a filter value"
    raise ValueError(msg)


def scope_regions(
    country_id: str,
    references: tuple[RegionReference, ...],
    release_manifest: object,
    *,
    reviewed_default: str,
) -> RegionScoping:
    """Give every runnable reference region its certified dataset and filter.

    The national region must use the reviewed default dataset. A region whose
    type has no scoping rule is left out, and a runnable region may not sit
    under a region that is left out.
    """
    if not isinstance(release_manifest, ReleaseManifest):
        msg = (
            f"{country_id} release manifest lacks datasets, region_datasets or "
            "data_package"
        )
        raise CatalogExtractionError(msg)
    artifacts = certified_artifacts(country_id, release_manifest)
    if reviewed_default not in artifacts:
        msg = f"{country_id} release does not certify {reviewed_default}"
        raise CatalogExtractionError(msg)
    role_datasets = _role_datasets(country_id, release_manifest, artifacts)
    if role_datasets.get(NATIONAL_DATASET_ROLE, reviewed_default) != reviewed_default:
        msg = f"{country_id} national region does not use the reviewed dataset"
        raise CatalogExtractionError(msg)

    omitted = {
        reference.code: reference.region_type
        for reference in references
        if (country_id, reference.region_type) not in REGION_SCOPING_RULES
    }
    fallback_counts: Counter[str] = Counter()
    regions: list[ScopedRegion] = []
    for reference in references:
        if reference.code in omitted:
            continue
        if reference.parent_code in omitted:
            msg = (
                f"region {reference.code!r} cannot be published because its parent "
                f"{reference.parent_code!r} is left out"
            )
            raise CatalogExtractionError(msg)
        rule = REGION_SCOPING_RULES[country_id, reference.region_type]
        _checked_filter_value(reference, rule)
        dataset_name = role_datasets.get(rule.dataset_role)
        if dataset_name is None:
            if rule.requires_release_dataset:
                msg = (
                    f"the {country_id} release routes no dataset to "
                    f"{rule.dataset_role} regions, so region {reference.code!r} "
                    "cannot select its households"
                )
                raise CatalogExtractionError(msg)
            dataset_name = reviewed_default
            if rule.dataset_role != NATIONAL_DATASET_ROLE:
                fallback_counts[reference.region_type] += 1
        regions.append(
            ScopedRegion(
                reference=reference,
                dataset_name=dataset_name,
                filter_strategy=rule.filter_strategy,
                filter_field=rule.filter_field,
            )
        )
    return RegionScoping(
        regions=tuple(regions),
        dataset_names=frozenset(
            {reviewed_default, *(region.dataset_name for region in regions)}
        ),
        certified_artifacts=artifacts,
        fallback_counts=dict(sorted(fallback_counts.items())),
        omitted_counts=dict(sorted(Counter(omitted.values()).items())),
    )


def filtered_artifacts(scoping: RegionScoping) -> tuple[CertifiedArtifact, ...]:
    """Return, by name, the datasets the regions' row filters read."""
    names = {
        region.dataset_name
        for region in scoping.regions
        if region.filter_strategy == ROW_FILTER
    }
    return tuple(scoping.certified_artifacts[name] for name in sorted(names))
