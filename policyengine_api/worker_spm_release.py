"""Validate the installed API bundle against the selected worker release registry."""

from importlib.metadata import version
import json
import sys

from policyengine_api.worker_spm import validate_worker_spm


class _RegistryCapability:
    def __init__(self, registry: dict):
        self.registry = registry

    def get_spm_capability(self, country, model_version, *, policyengine_version):
        capabilities = self.registry.get("spm_capabilities")
        return (
            capabilities.get(policyengine_version)
            if isinstance(capabilities, dict)
            else None
        )


def validate_installed_worker(registry: dict, expected_bundle: str) -> dict | None:
    """Fail before promotion if the selected worker cannot run this API bundle.

    Use the request validator directly: a legacy country can omit capability,
    while a canonical country requires certification and a matching forecast.
    """
    if version("policyengine") != expected_bundle:
        raise ValueError(
            "The installed PolicyEngine bundle differs from the release pin"
        )
    from policyengine_api.constants import POLICYENGINE_VERSION

    if POLICYENGINE_VERSION != expected_bundle:
        raise ValueError("The runtime-selected bundle differs from the release pin")
    routes = registry.get("policyengine") if isinstance(registry, dict) else None
    app = routes.get(expected_bundle) if isinstance(routes, dict) else None
    if not isinstance(app, str) or not app:
        raise ValueError("The selected bundle has no registered worker application")
    return validate_worker_spm(
        "us",
        gateway=_RegistryCapability(registry),
        policyengine_version=expected_bundle,
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m policyengine_api.worker_spm_release BUNDLE_VERSION"
        )
    selection = validate_installed_worker(json.load(sys.stdin), sys.argv[1])
    if selection is None:
        print(
            "Legacy API bundle is registered; canonical SPM capability is not required"
        )
    else:
        print("Installed API bundle and registered bundle's SPM capability agree")


if __name__ == "__main__":
    main()
