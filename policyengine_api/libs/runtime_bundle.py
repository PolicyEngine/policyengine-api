"""Resolve reproducibility metadata for simulation API runs.

The API has two dataset identities to keep straight:

* the worker URI, usually ``gs://...``, which Modal can read efficiently;
* the canonical artifact URI, usually ``hf://...@version``, which belongs in
  provenance and cache keys.

This module centralizes that mapping so economy runs do not silently lose the
data version before they are cached or sent to the worker.
"""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from pydantic import BaseModel

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

try:
    from policyengine.provenance.manifest import (
        CountryReleaseManifest,
        get_release_manifest,
        resolve_dataset_reference,
        resolve_region_dataset_path,
    )
except Exception:  # pragma: no cover - exercised only if pe.py import is broken.
    CountryReleaseManifest = Any  # type: ignore[misc,assignment]
    get_release_manifest = None
    resolve_dataset_reference = None
    resolve_region_dataset_path = None


_HF_TO_GS_REPOS = {
    "policyengine/policyengine-us-data": "gs://policyengine-us-data",
    "policyengine/policyengine-uk-data-private": "gs://policyengine-uk-data-private",
}


class RuntimeBundle(BaseModel):
    country_id: str
    bundle_id: str | None = None
    policyengine_version: str | None = None
    bundle_policyengine_version: str | None = None
    model_package: str | None = None
    model_version: str | None = None
    certified_model_version: str | None = None
    data_package: str | None = None
    data_version: str | None = None
    dataset: str
    canonical_dataset_uri: str | None = None
    worker_dataset_uri: str
    dataset_sha256: str | None = None
    compatibility_basis: str | None = None
    certified_by: str | None = None
    provenance_status: str

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def as_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["fingerprint"] = self.fingerprint
        return payload


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _strip_hf_revision(uri: str) -> tuple[str, str | None]:
    if "@" not in uri:
        return uri, None
    base, revision = uri.rsplit("@", 1)
    return base, revision


def _hf_to_worker_uri(uri: str) -> str:
    if not uri.startswith("hf://"):
        return uri

    without_scheme, _revision = _strip_hf_revision(uri[5:])
    parts = without_scheme.split("/", 2)
    if len(parts) != 3:
        return uri
    repo_id = f"{parts[0]}/{parts[1]}"
    path = parts[2]
    bucket = _HF_TO_GS_REPOS.get(repo_id)
    if bucket is None:
        return uri
    return f"{bucket}/{path}"


def _canonical_region_dataset_uri(
    country_id: str,
    region: str,
) -> str | None:
    if resolve_region_dataset_path is None:
        return None

    try:
        if region == country_id:
            return resolve_region_dataset_path(country_id, "national")

        if country_id == "us" and region.startswith("state/"):
            return resolve_region_dataset_path(
                "us",
                "state",
                state_code=region.split("/", 1)[1].upper(),
            )

        if country_id == "us" and region.startswith("congressional_district/"):
            return resolve_region_dataset_path(
                "us",
                "congressional_district",
                district_code=region.split("/", 1)[1].upper(),
            )

        if country_id == "us" and region.startswith("place/"):
            parent_state = region.split("/", 1)[1].split("-", 1)[0].upper()
            return resolve_region_dataset_path("us", "state", state_code=parent_state)
    except Exception:
        return None

    return None


def _manifest_for(country_id: str) -> CountryReleaseManifest | None:
    if get_release_manifest is None:
        return None
    try:
        return get_release_manifest(country_id)
    except Exception:
        return None


def resolve_runtime_bundle(
    *,
    country_id: str,
    region: str,
    dataset: str,
    requested_model_version: str | None = None,
) -> RuntimeBundle:
    """Resolve the model/data bundle for an API simulation request."""

    manifest = _manifest_for(country_id)
    canonical_dataset_uri: str | None = None
    dataset_name = dataset
    provenance_status = "unmanaged"

    if "://" in dataset:
        canonical_dataset_uri = dataset
    elif dataset == "default":
        canonical_dataset_uri = _canonical_region_dataset_uri(country_id, region)
        dataset_name = (
            manifest.default_dataset
            if manifest is not None and region == country_id
            else dataset
        )
        provenance_status = "managed"
    elif resolve_dataset_reference is not None:
        try:
            canonical_dataset_uri = resolve_dataset_reference(country_id, dataset)
            provenance_status = "managed"
        except Exception:
            canonical_dataset_uri = None

    if canonical_dataset_uri is None:
        worker_dataset_uri = dataset
        data_version = None
    else:
        worker_dataset_uri = _hf_to_worker_uri(canonical_dataset_uri)
        _base_uri, data_version = _strip_hf_revision(canonical_dataset_uri)

    certified_artifact = (
        manifest.certified_data_artifact if manifest is not None else None
    )
    certification = manifest.certification if manifest is not None else None
    model_version = requested_model_version or COUNTRY_PACKAGE_VERSIONS.get(country_id)

    return RuntimeBundle(
        country_id=country_id,
        bundle_id=manifest.bundle_id if manifest is not None else None,
        policyengine_version=_package_version("policyengine"),
        bundle_policyengine_version=(
            manifest.policyengine_version if manifest is not None else None
        ),
        model_package=(
            manifest.model_package.name if manifest is not None else None
        ),
        model_version=model_version,
        certified_model_version=(
            manifest.model_package.version if manifest is not None else None
        ),
        data_package=manifest.data_package.name if manifest is not None else None,
        data_version=(
            data_version
            or (manifest.data_package.version if manifest is not None else None)
        ),
        dataset=dataset_name,
        canonical_dataset_uri=canonical_dataset_uri,
        worker_dataset_uri=worker_dataset_uri,
        dataset_sha256=certified_artifact.sha256 if certified_artifact else None,
        compatibility_basis=(
            certification.compatibility_basis if certification is not None else None
        ),
        certified_by=certification.certified_by if certification is not None else None,
        provenance_status=provenance_status,
    )
