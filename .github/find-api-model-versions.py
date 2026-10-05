import argparse
import os
import shlex
import sys
from importlib.metadata import version as distribution_version

from policyengine.bundle import get_current_bundle
from policyengine_api.constants import (
    COUNTRY_PACKAGE_VERSIONS,
    POLICYENGINE_CORE_VERSION,
    POLICYENGINE_VERSION,
)

REQUIRED_PACKAGES = (
    "policyengine",
    "policyengine-core",
    "policyengine-us",
    "policyengine-uk",
    "spm-calculator",
)


def _manifest_versions(bundle: dict) -> dict[str, str]:
    packages = bundle.get("packages")
    if not isinstance(packages, dict):
        raise RuntimeError("PolicyEngine bundle manifest has no package mapping.")

    versions = {}
    for package_name in REQUIRED_PACKAGES:
        package = packages.get(package_name)
        if not isinstance(package, dict) or not package.get("version"):
            raise RuntimeError(
                f"PolicyEngine bundle manifest has no version for {package_name}."
            )
        versions[package_name] = str(package["version"])
    return versions


def _data_release_version(bundle: dict, country_id: str) -> str:
    data_releases = bundle.get("data_releases")
    release = data_releases.get(country_id) if isinstance(data_releases, dict) else None
    if not isinstance(release, dict) or not release.get("version"):
        raise RuntimeError(
            f"PolicyEngine bundle manifest has no {country_id.upper()} data release."
        )
    return str(release["version"])


def find_api_model_versions() -> dict[str, str]:
    """
    Find and validate the package and data versions in the installed bundle.
    """
    bundle = get_current_bundle()
    if not isinstance(bundle, dict):
        raise RuntimeError("Installed PolicyEngine bundle manifest is not an object.")

    manifest_versions = _manifest_versions(bundle)
    for package_name, manifest_version in manifest_versions.items():
        installed_version = distribution_version(package_name)
        if installed_version != manifest_version:
            raise RuntimeError(
                f"Installed {package_name} version {installed_version} does not match "
                f"bundle manifest version {manifest_version}."
            )

    expected_constants = {
        "policyengine": POLICYENGINE_VERSION,
        "policyengine-core": POLICYENGINE_CORE_VERSION,
        "policyengine-us": COUNTRY_PACKAGE_VERSIONS.get("us"),
        "policyengine-uk": COUNTRY_PACKAGE_VERSIONS.get("uk"),
    }
    for package_name, constant_version in expected_constants.items():
        if constant_version != manifest_versions[package_name]:
            raise RuntimeError(
                f"API version for {package_name} is {constant_version}, but the bundle "
                f"manifest specifies {manifest_versions[package_name]}."
            )

    return {
        "POLICYENGINE_VERSION": manifest_versions["policyengine"],
        "POLICYENGINE_CORE_VERSION": manifest_versions["policyengine-core"],
        "US_VERSION": manifest_versions["policyengine-us"],
        "UK_VERSION": manifest_versions["policyengine-uk"],
        "SPM_CALCULATOR_VERSION": manifest_versions["spm-calculator"],
        "US_DATA_VERSION": _data_release_version(bundle, "us"),
        "UK_DATA_VERSION": _data_release_version(bundle, "uk"),
    }


def find_api_model_versions_and_output_to_github():
    """
    Find the API model versions and output them to a file for GitHub.
    """
    versions = find_api_model_versions()
    with open(os.environ["GITHUB_ENV"], "a") as f:
        for key, value in versions.items():
            f.write(f"{key}={value}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--shell",
        action="store_true",
        help="Print shell-compatible KEY=VALUE lines instead of writing GITHUB_ENV.",
    )
    args = parser.parse_args()

    if args.shell:
        for key, value in find_api_model_versions().items():
            print(f"{key}={shlex.quote(value)}")
    else:
        find_api_model_versions_and_output_to_github()
        print("API model versions found and written to GitHub environment.")
    sys.exit(0)
