import os
import sys
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS


def find_api_model_versions_and_output_to_github():
    """
    Find the API model versions and output them to a file for GitHub.
    """
    # Try to get package versions for US and UK
    us_version = COUNTRY_PACKAGE_VERSIONS.get("us")
    uk_version = COUNTRY_PACKAGE_VERSIONS.get("uk")

    if not us_version:
        print("Error: US package version not found.", file=sys.stderr)
        sys.exit(1)

    if not uk_version:
        print("Error: UK package version not found.", file=sys.stderr)
        sys.exit(1)

    # Write to GitHub Actions environment
    with open(os.environ["GITHUB_ENV"], "a") as f:
        f.write(f"US_VERSION={us_version}\n")
        f.write(f"UK_VERSION={uk_version}\n")


if __name__ == "__main__":
    find_api_model_versions_and_output_to_github()
    print("API model versions found and written to GitHub environment.")
    sys.exit(0)
