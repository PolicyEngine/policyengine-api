"""Validate the installed API bundle against a simulation worker registry."""

from __future__ import annotations

from importlib.metadata import version as distribution_version
import json
import sys

from policyengine_api import constants
from policyengine_api.worker_spm import validate_worker_spm


REQUIRED_BUNDLE_PACKAGES = (
    "policyengine",
    "policyengine-core",
    "policyengine-us",
    "policyengine-uk",
    "spm-calculator",
)


class RegistryCapability:
    """Expose one registry document through the request validator interface."""

    def __init__(self, registry: dict):
        self.registry = registry

    def get_spm_capability(
        self,
        country,
        model_version,
        *,
        policyengine_version,
    ):
        capabilities = self.registry.get("spm_capabilities")
        if not isinstance(capabilities, dict):
            return None
        return capabilities.get(policyengine_version)


def _bundle_package_versions() -> dict[str, str]:
    bundle = constants._policyengine_bundle
    packages = bundle.get("packages") if isinstance(bundle, dict) else None
    if not isinstance(packages, dict):
        raise ValueError("The installed PolicyEngine bundle manifest has no packages")

    versions: dict[str, str] = {}
    for package_name in REQUIRED_BUNDLE_PACKAGES:
        package = packages.get(package_name)
        package_version = package.get("version") if isinstance(package, dict) else None
        if not isinstance(package_version, str) or not package_version:
            raise ValueError(f"The installed bundle does not identify {package_name}")
        versions[package_name] = package_version
    return versions


def _registered_application(
    registry: dict,
    route_kind: str,
    route_version: str,
) -> str:
    routes = registry.get(route_kind) if isinstance(registry, dict) else None
    app = routes.get(route_version) if isinstance(routes, dict) else None
    if not isinstance(app, str) or not app:
        raise ValueError(
            f"The worker registry has no {route_kind} {route_version} application"
        )
    return app


def validate_installed_worker(registry: dict, expected_bundle: str) -> dict | None:
    """Validate local package versions, worker routes, and SPM capability."""
    versions = _bundle_package_versions()
    if versions["policyengine"] != expected_bundle:
        raise ValueError("The bundle manifest differs from the release requirement")
    if constants.POLICYENGINE_VERSION != expected_bundle:
        raise ValueError("The API runtime differs from the release requirement")

    for package_name, expected_version in versions.items():
        if distribution_version(package_name) != expected_version:
            raise ValueError(
                f"Installed {package_name} does not match the bundle manifest"
            )

    bundle_app = _registered_application(registry, "policyengine", expected_bundle)
    for country_id, package_name in (
        ("us", "policyengine-us"),
        ("uk", "policyengine-uk"),
    ):
        country_app = _registered_application(
            registry,
            country_id,
            versions[package_name],
        )
        if country_app != bundle_app:
            raise ValueError(
                f"The {country_id} route resolves to a different worker application"
            )

    return validate_worker_spm(
        "us",
        gateway=RegistryCapability(registry),
        policyengine_version=expected_bundle,
        model_version=versions["policyengine-us"],
    )


def main() -> None:
    """Read a registry document from stdin and validate one bundle version."""
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m policyengine_api.worker_spm_release BUNDLE_VERSION"
        )
    selection = validate_installed_worker(json.load(sys.stdin), sys.argv[1])
    if selection is None:
        print("The installed legacy bundle and registered worker agree")
    else:
        print("The installed bundle and registered worker capability agree")


if __name__ == "__main__":
    main()
