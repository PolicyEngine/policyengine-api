import argparse
import os
import re
import time


def main():
    parser = argparse.ArgumentParser()
    # Usage: python bump_country_package.py --country=policyengine-uk --version=1.0.1
    # Country can be: policyengine-uk, policyengine-us
    # Version should be in the format: 1.0.1
    parser.add_argument(
        "--country",
        type=str,
        required=True,
        help="Country package to bump",
        choices=["policyengine-uk", "policyengine-us", "policyengine-canada"],
    )
    parser.add_argument("--version", type=str, required=True, help="Version to bump to")
    args = parser.parse_args()
    country = args.country
    version = args.version
    bump_country_package(country, version)


def bump_country_package(country, version):
    time.sleep(60 * 5)
    # Update the version in pyproject.toml
    pyproject_path = "pyproject.toml"
    with open(pyproject_path, "r") as f:
        pyproject = f.read()
    # Find where it says {country}=={old version} and replace it with {country}=={new version}
    country_package_name = country.replace("-", "_")
    package_version_regex = rf"{country_package_name}==(\d+\.\d+\.\d+)"
    match = re.search(package_version_regex, pyproject)

    # If the line was found, replace it with the new package version
    if match:
        new_line = f"{country_package_name}=={version}"
        pyproject = pyproject.replace(match.group(0), new_line)
    # Write updated pyproject.toml
    with open(pyproject_path, "w") as f:
        f.write(pyproject)

    country_package_full_name = country.replace("policyengine", "PolicyEngine").replace(
        "-", " "
    )
    country_id = country.replace("policyengine-", "")
    country_package_full_name = country_package_full_name.replace(
        country_id, country_id.upper()
    )

    # Define branch name (needed for changelog fragment filename)
    branch_name = f"bump-{country}-to-{version}"

    # Create a changelog fragment in changelog.d/
    changelog_content = f"Update {country_package_full_name} to {version}.\n"
    fragment_path = f"changelog.d/{branch_name}.changed.md"
    with open(fragment_path, "w") as f:
        f.write(changelog_content)
    # Checkout a new branch locally, add all the files, commit, and push using the GitHub CLI only

    # First, create a new branch off master
    os.system(f"git checkout -b {branch_name}")
    # Add all the files
    os.system("git add -A")
    # Commit the change
    os.system(f"git config --global user.name 'PolicyEngine[bot]'")
    os.system(f"git config --global user.email 'hello@policyengine.org'")
    os.system(f'git commit -m "Bump {country_package_full_name} to {version}"')
    # Push the branch to GitHub, using the personal access token stored in GITHUB_TOKEN
    os.system(f"git push -u origin {branch_name} -f")
    # Create a pull request using the GitHub CLI
    os.system(
        f"gh pr create --title 'Update {country_package_full_name} to {version}' --body 'Update {country_package_full_name} to {version}' --base master --head {branch_name}"
    )


if __name__ == "__main__":
    main()
