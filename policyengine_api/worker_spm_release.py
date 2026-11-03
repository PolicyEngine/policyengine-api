"""Validate the installed API bundle against a simulation worker registry."""

from __future__ import annotations

import json
import sys
from importlib.metadata import version as distribution_version

from typing_extensions import override

from policyengine_api import constants
from policyengine_api.worker_spm import SPMCapabilitySource, validate_worker_spm

# The command line is the program name followed by the bundle version.
COMMAND_LINE_LENGTH = 2
REQUIRED_BUNDLE_PACKAGES = (
    "policyengine",
    "policyengine-core",
    "policyengine-us",
    "policyengine-uk",
    "spm-calculator",
)


class RegistryCapability(SPMCapabilitySource):
    """Expose one registry document through the request validator interface."""

    def __init__(self, registry: dict) -> None:
        """Wrap a parsed worker registry document."""
        self.registry = registry

    @override
    def get_spm_capability(
        self,
        country: str,
        model_version: str | None,
        *,
        policyengine_version: str | None,
    ) -> object:
        """Return the registry's SPM capability for ``policyengine_version``, or None.

        The registry keys capabilities by PolicyEngine.py version alone, so
        ``country`` and ``model_version`` are not consulted.
        """
        capabilities = self.registry.get("spm_capabilities")
        if not isinstance(capabilities, dict):
            return None
        return capabilities.get(policyengine_version)


def _bundle_package_versions() -> dict[str, str]:
    bundle = constants.get_bundle_manifest()
    packages = bundle.get("packages") if isinstance(bundle, dict) else None
    if not isinstance(packages, dict):
        msg = "The installed PolicyEngine bundle manifest has no packages"
        raise TypeError(msg)

    versions: dict[str, str] = {}
    for package_name in REQUIRED_BUNDLE_PACKAGES:
        package = packages.get(package_name)
        package_version = package.get("version") if isinstance(package, dict) else None
        if not isinstance(package_version, str) or not package_version:
            msg = f"The installed bundle does not identify {package_name}"
            raise ValueError(msg)
        versions[package_name] = package_version
    return versions


def validate_installed_worker(registry: dict, expected_bundle: str) -> dict | None:
    """Validate local package versions and the worker's SPM capability.

    ``.github/request-simulation-model-versions.sh`` checks the registry's
    PolicyEngine.py routes before this runs. The gateway routes the Public
    API's requests by PolicyEngine.py version, so the US and UK routes are not
    compared.
    """
    versions = _bundle_package_versions()
    if versions["policyengine"] != expected_bundle:
        msg = "The bundle manifest differs from the release requirement"
        raise ValueError(msg)
    if expected_bundle != constants.POLICYENGINE_VERSION:
        msg = "The API runtime differs from the release requirement"
        raise ValueError(msg)

    for package_name, expected_version in versions.items():
        if distribution_version(package_name) != expected_version:
            msg = f"Installed {package_name} does not match the bundle manifest"
            raise ValueError(msg)

    return validate_worker_spm(
        "us",
        gateway=RegistryCapability(registry),
        policyengine_version=expected_bundle,
        model_version=versions["policyengine-us"],
    )


def main() -> None:
    """Read a registry document from stdin and validate one bundle version."""
    if len(sys.argv) != COMMAND_LINE_LENGTH:
        msg = "Usage: python -m policyengine_api.worker_spm_release BUNDLE_VERSION"
        raise SystemExit(msg)
    selection = validate_installed_worker(json.load(sys.stdin), sys.argv[1])
    if selection is None:
        print("The installed legacy bundle and registered worker agree")
    else:
        print("The installed bundle and registered worker capability agree")


if __name__ == "__main__":
    main()
