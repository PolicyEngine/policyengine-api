"""Serialize execution provenance using policyengine.py's receipt v1 contract.

PolicyEngine API currently pins a policyengine.py release that predates the
``ExecutionReceipt`` Pydantic model. This module is a compatibility serializer,
not a competing schema: its exact output is pinned by the v1 contract fixture
under ``tests/fixtures/execution_receipt_v1.json``.
"""

from collections.abc import Mapping
from datetime import datetime
import hashlib
import hmac
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import rfc8785

from policyengine_api.constants import (
    BUNDLED_COUNTRY_PACKAGE_NAMES,
    get_policyengine_bundle_manifest,
)


EXECUTION_RECEIPT_SCHEMA_VERSION = 1
SHA256_LENGTH = 64
REQUESTED_ALIAS_FIELDS = (
    "engine",
    "bundle",
    "model",
    "data",
    "ruleset",
    "population",
    "numeric_mode",
)

EXECUTION_RECEIPT_FIELDS = {
    "schema_version",
    "requested",
    "resolved",
    "run_id",
    "created_at",
    "request_sha256",
    "result_sha256",
}
RESOLVED_EXECUTION_FIELDS = {
    "runtime",
    "numeric_mode",
    "model",
    "data",
    "ruleset_artifact",
    "population_artifact",
    "certified_release",
    "bundle_trace",
}
RESULT_PROVENANCE_FIELDS = {
    "execution_receipt",
    "policyengine_bundle",
    "resolved_app_name",
}


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _is_optional_string(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _is_optional_datetime(value: Any) -> bool:
    if value is None:
        return True
    if not _is_nonempty_string(value) or "T" not in value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _is_sha256(value: Any, *, nullable: bool = True) -> bool:
    if value is None:
        return nullable
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _has_only_fields(value: Mapping[str, Any], fields: set[str]) -> bool:
    return all(isinstance(key, str) and key in fields for key in value)


def _is_package_version(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if not _has_only_fields(value, {"name", "version", "sha256", "wheel_url"}):
        return False
    return (
        _is_nonempty_string(value.get("name"))
        and _is_nonempty_string(value.get("version"))
        and _is_sha256(value.get("sha256"))
        and _is_optional_string(value.get("wheel_url"))
    )


def _is_data_package_version(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    fields = {
        "name",
        "version",
        "sha256",
        "wheel_url",
        "repo_id",
        "repo_type",
        "release_manifest_path",
        "release_manifest_revision",
    }
    if not _has_only_fields(value, fields):
        return False
    return (
        _is_nonempty_string(value.get("name"))
        and _is_nonempty_string(value.get("version"))
        and _is_sha256(value.get("sha256"))
        and _is_optional_string(value.get("wheel_url"))
        and _is_nonempty_string(value.get("repo_id"))
        and _is_nonempty_string(value.get("repo_type"))
        and _is_nonempty_string(value.get("release_manifest_path"))
        and _is_optional_string(value.get("release_manifest_revision"))
    )


def _is_package_resolution(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, Mapping):
        return False
    if not _has_only_fields(value, {"actual", "certified"}):
        return False
    actual = value.get("actual")
    certified = value.get("certified")
    if actual is None:
        return False
    return _is_package_version(actual) and (
        certified is None or _is_package_version(certified)
    )


def _is_artifact_identity(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, Mapping):
        return False
    fields = {"name", "version", "uri", "revision", "sha256", "build_id"}
    if not _has_only_fields(value, fields) or not _is_nonempty_string(
        value.get("name")
    ):
        return False
    if not _is_sha256(value.get("sha256")):
        return False
    identity_fields = ("version", "uri", "revision", "sha256", "build_id")
    if not all(_is_optional_string(value.get(field)) for field in identity_fields):
        return False
    return any(value.get(field) for field in identity_fields)


def _is_runtime_identity(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if not _has_only_fields(value, {"name", "version", "git_sha", "artifact"}):
        return False
    return (
        _is_nonempty_string(value.get("name"))
        and _is_nonempty_string(value.get("version"))
        and _is_optional_string(value.get("git_sha"))
        and _is_artifact_identity(value.get("artifact"))
    )


def _is_trace_reference(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, Mapping):
        return False
    if not _has_only_fields(
        value, {"composition_fingerprint", "sha256", "url", "name"}
    ):
        return False
    return (
        _is_sha256(value.get("composition_fingerprint"), nullable=False)
        and _is_sha256(value.get("sha256"))
        and _is_optional_string(value.get("url"))
        and _is_optional_string(value.get("name"))
    )


def _is_artifact_path_reference(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    fields = {
        "path",
        "revision",
        "sha256",
        "metadata_sha256",
        "repo_id",
        "repo_type",
    }
    return (
        _has_only_fields(value, fields)
        and _is_nonempty_string(value.get("path"))
        and _is_optional_string(value.get("revision"))
        and _is_sha256(value.get("sha256"))
        and _is_sha256(value.get("metadata_sha256"))
        and _is_optional_string(value.get("repo_id"))
        and _is_optional_string(value.get("repo_type"))
    )


def _is_artifact_path_template(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and _has_only_fields(value, {"path_template"})
        and _is_nonempty_string(value.get("path_template"))
    )


def _is_certified_data_artifact(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, Mapping):
        return False
    fields = {"data_package", "dataset", "uri", "sha256", "build_id"}
    data_package = value.get("data_package")
    return (
        _has_only_fields(value, fields)
        and (data_package is None or _is_package_version(data_package))
        and _is_nonempty_string(value.get("dataset"))
        and _is_nonempty_string(value.get("uri"))
        and _is_sha256(value.get("sha256"))
        and _is_optional_string(value.get("build_id"))
    )


def _is_data_certification(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, Mapping):
        return False
    fields = {
        "compatibility_basis",
        "certified_for_model_version",
        "data_build_id",
        "built_with_model_version",
        "built_with_model_git_sha",
        "data_build_fingerprint",
        "certified_by",
    }
    return (
        _has_only_fields(value, fields)
        and _is_nonempty_string(value.get("compatibility_basis"))
        and _is_nonempty_string(value.get("certified_for_model_version"))
        and all(
            _is_optional_string(value.get(field))
            for field in fields - {"compatibility_basis", "certified_for_model_version"}
        )
    )


def _is_country_release_manifest(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, Mapping):
        return False
    fields = {
        "schema_version",
        "bundle_id",
        "published_at",
        "country_id",
        "policyengine_version",
        "model_package",
        "data_package",
        "default_dataset",
        "datasets",
        "region_datasets",
        "certified_data_artifact",
        "certification",
    }
    if not _has_only_fields(value, fields):
        return False
    datasets = value.get("datasets")
    region_datasets = value.get("region_datasets")
    return (
        isinstance(value.get("schema_version"), int)
        and not isinstance(value.get("schema_version"), bool)
        and _is_optional_string(value.get("bundle_id"))
        and _is_optional_string(value.get("published_at"))
        and _is_nonempty_string(value.get("country_id"))
        and _is_nonempty_string(value.get("policyengine_version"))
        and _is_package_version(value.get("model_package"))
        and _is_data_package_version(value.get("data_package"))
        and _is_nonempty_string(value.get("default_dataset"))
        and isinstance(datasets, Mapping)
        and all(
            _is_nonempty_string(name) and _is_artifact_path_reference(artifact)
            for name, artifact in datasets.items()
        )
        and isinstance(region_datasets, Mapping)
        and all(
            _is_nonempty_string(name) and _is_artifact_path_template(template)
            for name, template in region_datasets.items()
        )
        and _is_certified_data_artifact(value.get("certified_data_artifact"))
        and _is_data_certification(value.get("certification"))
    )


def is_valid_execution_receipt(value: Any) -> bool:
    """Return whether an untrusted worker value satisfies receipt v1.

    This deliberately validates engine-neutral fields instead of requiring a
    PolicyEngine runtime name, so valid Axiom receipts pass through unchanged.
    Certified release context is checked against the same fully specified
    manifest shape published in OpenAPI.
    """
    if not isinstance(value, Mapping):
        return False
    if not _has_only_fields(value, EXECUTION_RECEIPT_FIELDS):
        return False
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != EXECUTION_RECEIPT_SCHEMA_VERSION
    ):
        return False

    requested = value.get("requested")
    if not isinstance(requested, Mapping):
        return False
    if not _has_only_fields(requested, set(REQUESTED_ALIAS_FIELDS)):
        return False
    if not all(_is_optional_string(requested.get(field)) for field in requested):
        return False

    resolved = value.get("resolved")
    if not isinstance(resolved, Mapping):
        return False
    if not _has_only_fields(resolved, RESOLVED_EXECUTION_FIELDS):
        return False
    if not _is_runtime_identity(resolved.get("runtime")):
        return False
    if not _is_nonempty_string(resolved.get("numeric_mode")):
        return False
    if not _is_package_resolution(resolved.get("model")):
        return False
    if not _is_package_resolution(resolved.get("data")):
        return False
    if not _is_artifact_identity(resolved.get("ruleset_artifact")):
        return False
    if not _is_artifact_identity(resolved.get("population_artifact")):
        return False
    certified_release = resolved.get("certified_release")
    if not _is_country_release_manifest(certified_release):
        return False
    if not _is_trace_reference(resolved.get("bundle_trace")):
        return False

    if certified_release is not None:
        for component, release_field in (
            (resolved.get("model"), "model_package"),
            (resolved.get("data"), "data_package"),
        ):
            if not isinstance(component, Mapping):
                continue
            certified = component.get("certified")
            if certified is None:
                continue
            release_package = certified_release[release_field]
            for field in ("name", "version", "sha256", "wheel_url"):
                claimed_value = certified.get(field)
                if claimed_value is not None and claimed_value != release_package.get(
                    field
                ):
                    return False

    return (
        _is_optional_string(value.get("run_id"))
        and _is_optional_datetime(value.get("created_at"))
        and _is_sha256(value.get("request_sha256"))
        and _is_sha256(value.get("result_sha256"))
    )


def _get_installed_package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def _canonical_content_sha256(value: Mapping[str, Any]) -> str:
    """Hash RFC 8785 JCS bytes for Rust/TypeScript/Python parity."""
    try:
        canonical_bytes = rfc8785.dumps(value)
    except rfc8785.FloatDomainError as exc:
        raise ValueError(
            "Execution receipt hashes require finite JSON numbers."
        ) from exc
    return hashlib.sha256(canonical_bytes).hexdigest()


def execution_result_sha256(result: Mapping[str, Any]) -> str:
    """Hash the calculation result without provenance/enrichment siblings.

    Workers, caches, and this compatibility serializer all use this same target.
    Adding an execution receipt, a PolicyEngine bundle, or a resolved app name
    therefore does not invalidate a receipt for otherwise identical output.
    """
    calculation_result = {
        key: value
        for key, value in result.items()
        if key not in RESULT_PROVENANCE_FIELDS
    }
    return _canonical_content_sha256(calculation_result)


def execution_receipt_matches_result(
    receipt: Any,
    result: Mapping[str, Any],
) -> bool:
    """Return whether a valid receipt cryptographically binds ``result``."""
    if not is_valid_execution_receipt(receipt):
        return False
    claimed_sha256 = receipt.get("result_sha256")
    if not isinstance(claimed_sha256, str):
        return False
    return hmac.compare_digest(claimed_sha256, execution_result_sha256(result))


def execution_receipt_runtime_name(receipt: Any) -> str | None:
    """Read a claimed runtime name even from an unsupported receipt schema."""
    if not isinstance(receipt, Mapping):
        return None
    resolved = receipt.get("resolved")
    if not isinstance(resolved, Mapping):
        return None
    runtime = resolved.get("runtime")
    if not isinstance(runtime, Mapping):
        return None
    return _optional_string(runtime.get("name"))


def _package_version(value: Any) -> dict[str, str | None] | None:
    if not isinstance(value, Mapping):
        return None
    name = _optional_string(value.get("name"))
    package_version = _optional_string(value.get("version"))
    if name is None or package_version is None:
        return None
    return {
        "name": name,
        "version": package_version,
        "sha256": _optional_string(value.get("sha256")),
        "wheel_url": _optional_string(value.get("wheel_url")),
    }


def _actual_package(name: str | None, package_version: str | None) -> dict | None:
    if name is None or package_version is None:
        return None
    return {
        "name": name,
        "version": package_version,
        "sha256": None,
        "wheel_url": None,
    }


def _data_package_version(value: Any) -> dict | None:
    package = _package_version(value)
    if package is None or not isinstance(value, Mapping):
        return None
    repo_id = _optional_string(value.get("repo_id"))
    if repo_id is None:
        return None
    return {
        **package,
        "repo_id": repo_id,
        "repo_type": _optional_string(value.get("repo_type")) or "model",
        "release_manifest_path": (
            _optional_string(value.get("release_manifest_path"))
            or "release_manifest.json"
        ),
        "release_manifest_revision": _optional_string(
            value.get("release_manifest_revision")
        ),
    }


def _artifact_path_reference(value: Any) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    path = _optional_string(value.get("path"))
    if path is None:
        return None
    return {
        "path": path,
        "revision": _optional_string(value.get("revision")),
        "sha256": _optional_string(value.get("sha256")),
        "metadata_sha256": _optional_string(value.get("metadata_sha256")),
        "repo_id": _optional_string(value.get("repo_id")),
        "repo_type": _optional_string(value.get("repo_type")),
    }


def _certified_data_artifact(value: Any) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    dataset = _optional_string(value.get("dataset"))
    uri = _optional_string(value.get("uri"))
    if dataset is None or uri is None:
        return None
    return {
        "data_package": _package_version(value.get("data_package")),
        "dataset": dataset,
        "uri": uri,
        "sha256": _optional_string(value.get("sha256")),
        "build_id": _optional_string(value.get("build_id")),
    }


def _certification(value: Any) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    compatibility_basis = _optional_string(value.get("compatibility_basis"))
    certified_for_model_version = _optional_string(
        value.get("certified_for_model_version")
    )
    if compatibility_basis is None or certified_for_model_version is None:
        return None
    return {
        "compatibility_basis": compatibility_basis,
        "certified_for_model_version": certified_for_model_version,
        "data_build_id": _optional_string(value.get("data_build_id")),
        "built_with_model_version": _optional_string(
            value.get("built_with_model_version")
        ),
        "built_with_model_git_sha": _optional_string(
            value.get("built_with_model_git_sha")
        ),
        "data_build_fingerprint": _optional_string(value.get("data_build_fingerprint")),
        "certified_by": _optional_string(value.get("certified_by")),
    }


def _serialize_certified_release(value: Any) -> dict | None:
    """Filter a bundled release to CountryReleaseManifest's declared fields."""
    if not isinstance(value, Mapping):
        return None
    model_package = _package_version(value.get("model_package"))
    data_package = _data_package_version(value.get("data_package"))
    country_id = _optional_string(value.get("country_id"))
    policyengine_version = _optional_string(value.get("policyengine_version"))
    default_dataset = _optional_string(value.get("default_dataset"))
    if (
        model_package is None
        or data_package is None
        or country_id is None
        or policyengine_version is None
        or default_dataset is None
    ):
        return None

    datasets = {}
    raw_datasets = value.get("datasets")
    if isinstance(raw_datasets, Mapping):
        for name, raw_artifact in raw_datasets.items():
            artifact = _artifact_path_reference(raw_artifact)
            if artifact is not None:
                datasets[str(name)] = artifact

    region_datasets = {}
    raw_region_datasets = value.get("region_datasets")
    if isinstance(raw_region_datasets, Mapping):
        for name, raw_template in raw_region_datasets.items():
            if not isinstance(raw_template, Mapping):
                continue
            path_template = _optional_string(raw_template.get("path_template"))
            if path_template is not None:
                region_datasets[str(name)] = {"path_template": path_template}

    schema_version = value.get("schema_version", 1)
    if not isinstance(schema_version, int):
        return None

    serialized_release = {
        "schema_version": schema_version,
        "bundle_id": _optional_string(value.get("bundle_id")),
        "published_at": _optional_string(value.get("published_at")),
        "country_id": country_id,
        "policyengine_version": policyengine_version,
        "model_package": model_package,
        "data_package": data_package,
        "default_dataset": default_dataset,
        "datasets": datasets,
        "region_datasets": region_datasets,
        "certified_data_artifact": _certified_data_artifact(
            value.get("certified_data_artifact")
        ),
        "certification": _certification(value.get("certification")),
    }
    return (
        serialized_release if _is_country_release_manifest(serialized_release) else None
    )


def _release_for_runtime(
    country_id: str,
    policyengine_version: str | None,
) -> dict | None:
    """Return the certified context only when it matches the selected bundle."""
    if policyengine_version is None:
        return None
    manifest = get_policyengine_bundle_manifest()
    if not isinstance(manifest, Mapping):
        return None
    data_releases = manifest.get("data_releases")
    if not isinstance(data_releases, Mapping):
        return None
    release = data_releases.get(country_id)
    if not isinstance(release, Mapping):
        return None
    if _optional_string(release.get("policyengine_version")) != policyengine_version:
        return None
    return _serialize_certified_release(release)


def _requested_aliases(values: Mapping[str, Any] | None = None) -> dict:
    values = values if isinstance(values, Mapping) else {}
    return {
        field: _optional_string(values.get(field)) for field in REQUESTED_ALIAS_FIELDS
    }


def _runtime_identity(
    *,
    name: str,
    runtime_version: str,
    artifact_name: str | None = None,
) -> dict:
    artifact = None
    if artifact_name is not None:
        artifact = {
            "name": artifact_name,
            "version": runtime_version,
            "uri": None,
            "revision": None,
            "sha256": None,
            "build_id": None,
        }
    return {
        "name": name,
        "version": runtime_version,
        "git_sha": None,
        "artifact": artifact,
    }


def _artifact_revision(uri: str | None) -> str | None:
    if uri is None or "@" not in uri:
        return None
    return uri.rsplit("@", 1)[1] or None


def _receipt(
    *,
    requested: Mapping[str, Any] | None,
    runtime: dict,
    model: dict | None,
    data: dict | None,
    population_artifact: dict | None,
    certified_release: dict | None,
    run_id: str | None,
    request_payload: Mapping[str, Any] | None,
    result: Mapping[str, Any],
) -> dict | None:
    receipt = {
        "schema_version": EXECUTION_RECEIPT_SCHEMA_VERSION,
        "requested": _requested_aliases(requested),
        "resolved": {
            "runtime": runtime,
            "numeric_mode": "numpy-native",
            "model": model,
            "data": data,
            "ruleset_artifact": None,
            "population_artifact": population_artifact,
            "certified_release": certified_release,
            "bundle_trace": None,
        },
        "run_id": _optional_string(run_id),
        "created_at": None,
        "request_sha256": (
            _canonical_content_sha256(request_payload)
            if request_payload is not None
            else None
        ),
        "result_sha256": execution_result_sha256(result),
    }
    return receipt if is_valid_execution_receipt(receipt) else None


def build_household_execution_receipt(
    *,
    country_id: str,
    request_payload: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict | None:
    """Build a receipt for an in-process household calculation."""
    runtime_version = _get_installed_package_version("policyengine-core")
    if runtime_version is None:
        return None

    bundle_version = _get_installed_package_version("policyengine")
    certified_release = _release_for_runtime(country_id, bundle_version)
    model_name = BUNDLED_COUNTRY_PACKAGE_NAMES.get(country_id)
    actual_model = _actual_package(
        model_name,
        _get_installed_package_version(model_name) if model_name is not None else None,
    )
    certified_model = (
        certified_release.get("model_package")
        if certified_release is not None
        else None
    )
    model = None
    if actual_model is not None:
        model = {"actual": actual_model, "certified": certified_model}

    hashed_request = {"country_id": country_id, **dict(request_payload)}
    return _receipt(
        requested=None,
        runtime=_runtime_identity(
            name="policyengine-core",
            runtime_version=runtime_version,
        ),
        model=model,
        data=None,
        population_artifact=None,
        certified_release=certified_release,
        run_id=None,
        request_payload=hashed_request,
        result=result,
    )


def build_economy_execution_receipt(
    *,
    country_id: str,
    policyengine_bundle: Mapping[str, Any],
    result: Mapping[str, Any],
    requested: Mapping[str, Any] | None = None,
    resolved_app_name: str | None = None,
    run_id: str | None = None,
) -> dict | None:
    """Build a receipt from the economy worker's resolved runtime bundle."""
    runtime_version = _optional_string(policyengine_bundle.get("policyengine_version"))
    if runtime_version is None:
        return None

    certified_release = _release_for_runtime(country_id, runtime_version)
    model_name = BUNDLED_COUNTRY_PACKAGE_NAMES.get(country_id)
    if model_name is None and certified_release is not None:
        model_name = certified_release["model_package"]["name"]
    actual_model = _actual_package(
        model_name,
        _optional_string(policyengine_bundle.get("model_version")),
    )
    certified_model = (
        certified_release.get("model_package")
        if certified_release is not None
        else None
    )
    model = None
    if actual_model is not None:
        model = {"actual": actual_model, "certified": certified_model}

    dataset = _optional_string(policyengine_bundle.get("dataset"))
    data_version = _optional_string(policyengine_bundle.get("data_version"))
    if dataset in (None, "default") or data_version is None or "://" not in dataset:
        return None

    population_artifact = None
    data = None
    certified_artifact = (
        certified_release.get("certified_data_artifact")
        if certified_release is not None
        else None
    )
    artifact_matches_certification = bool(
        certified_artifact is not None
        and dataset == certified_artifact.get("uri")
        and data_version == certified_artifact.get("build_id")
    )
    artifact_name = (
        certified_artifact["dataset"] if artifact_matches_certification else dataset
    )
    candidate_population_artifact = {
        "name": artifact_name,
        "version": None,
        "uri": dataset,
        "revision": _artifact_revision(dataset),
        "sha256": (
            certified_artifact.get("sha256") if artifact_matches_certification else None
        ),
        "build_id": data_version,
    }
    if _is_artifact_identity(candidate_population_artifact):
        population_artifact = candidate_population_artifact
    certified_data = (
        _package_version(certified_release.get("data_package"))
        if certified_release is not None
        else None
    )
    actual_data = (
        certified_artifact.get("data_package")
        if artifact_matches_certification
        else None
    )
    if actual_data is not None:
        data = {"actual": actual_data, "certified": certified_data}

    return _receipt(
        requested=requested,
        runtime=_runtime_identity(
            name="policyengine",
            runtime_version=runtime_version,
            artifact_name=_optional_string(resolved_app_name),
        ),
        model=model,
        data=data,
        population_artifact=population_artifact,
        certified_release=certified_release,
        run_id=run_id,
        request_payload=None,
        result=result,
    )
