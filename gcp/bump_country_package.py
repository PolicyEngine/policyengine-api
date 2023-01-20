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
    parser.add_argument(
        "--version", type=str, required=True, help="Version to bump to"
    )
    args = parser.parse_args()
    country = args.country
    version = args.version
    bump_country_package(country, version)


def bump_country_package(country, version):
    time.sleep(60 * 5)
    # Update the version in the country package's setup.py
    setup_py_path = f"setup.py"
    with open(setup_py_path, "r") as f:
        setup_py = f.read()
    # Find where it says {country}=={old version} and replace it with {country}=={new version}
    country_package_name = country.replace("-", "_")
    package_version_regex = rf"{country_package_name}==(\d+\.\d+\.\d+)"
    match = re.search(package_version_regex, setup_py)

    # If the line was found, replace it with the new package version
    if match:
        new_line = f"{country_package_name}=={version}"
    setup_py = setup_py.replace(match.group(0), new_line)
    # Write setup_py to setup.py
    with open(setup_py_path, "w") as f:
        f.write(setup_py)

    changelog_yaml = f"""- bump: patch\n  changes:\n    changed:\n    - Bump {country} to {version}\n"""
    # Write changelog_yaml to changelog.yaml
    with open("changelog_entry.yaml", "w") as f:
        f.write(changelog_yaml)

    # Commit the change and push to a branch
    branch_name = f"bump-{country}-to-{version}"
    # Checkout a new branch locally, add all the files, commit, and push using the GitHub CLI only

    # First, create a new branch off master
    os.system(f"git checkout -b {branch_name}")
    # Add all the files
    os.system("git add -A")
    # Commit the change
    os.system(f"git config --global user.name 'PolicyEngine[bot]'")
    os.system(f"git config --global user.email 'hello@policyengine.org'")
    os.system(f'git commit -m "Bump {country} to {version}"')
    # Push the branch to GitHub, using the personal access token stored in GITHUB_TOKEN
    os.system(f"git push -u origin {branch_name} -f")
    # Create a pull request using the GitHub CLI
    os.system(
        f"gh pr create --title 'Bump {country} to {version}' --body 'Bump {country} to {version}' --base master --head {branch_name}"
    )


if __name__ == "__main__":
    main()
