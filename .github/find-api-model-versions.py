import argparse
import os
import sys

from policyengine_api.constants import (
    COUNTRY_PACKAGE_VERSIONS,
    POLICYENGINE_CORE_VERSION,
    POLICYENGINE_VERSION,
)


def find_api_model_versions() -> dict[str, str]:
    """
    Find the API model versions from the installed PolicyEngine bundle.
    """
    us_version = COUNTRY_PACKAGE_VERSIONS.get("us")
    uk_version = COUNTRY_PACKAGE_VERSIONS.get("uk")

    if not us_version:
        print("Error: US package version not found.", file=sys.stderr)
        sys.exit(1)

    if not uk_version:
        print("Error: UK package version not found.", file=sys.stderr)
        sys.exit(1)

    if not POLICYENGINE_VERSION:
        print("Error: PolicyEngine package version not found.", file=sys.stderr)
        sys.exit(1)

    return {
        "POLICYENGINE_VERSION": POLICYENGINE_VERSION,
        "POLICYENGINE_CORE_VERSION": POLICYENGINE_CORE_VERSION,
        "US_VERSION": us_version,
        "UK_VERSION": uk_version,
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
            print(f"{key}={value}")
    else:
        find_api_model_versions_and_output_to_github()
        print("API model versions found and written to GitHub environment.")
    sys.exit(0)
