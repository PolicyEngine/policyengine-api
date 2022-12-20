import argparse
import os


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
        choices=["policyengine-uk", "policyengine-us"],
    )
    parser.add_argument(
        "--version", type=str, required=True, help="Version to bump to"
    )
    args = parser.parse_args()
    country = args.country
    version = args.version
    bump_country_package(country, version)


def bump_country_package(country, version):
    # Update the version in the country package's setup.py
    setup_py_path = f"setup.py"
    with open(setup_py_path, "r") as f:
        setup_py = f.read()
    # Find where it says {country}=={old version} and replace it with {country}=={new version}
    old_version = setup_py.split(f"{country.replace('-', '_')}==")[1].split(
        " "
    )[0]
    setup_py = setup_py.replace(
        f"{country}=={old_version}", f"{country}=={version}"
    )
    with open(setup_py_path, "w") as f:
        f.write(setup_py)
    # In policyengine_api/constants.py, update the version (there's a VERSION = "x.x.x" line)
    constants_py_path = "policyengine_api/constants.py"
    with open(constants_py_path, "r") as f:
        constants_py = f.read()
        # Find where it says VERSION = "{old version}" and replace it with VERSION = "{new version}"
        old_version = (
            constants_py.split("VERSION = ")[1].split(" ")[0].replace('"', "")
        )
        constants_py = constants_py.replace(
            f'VERSION = "{old_version}"', f'VERSION = "{version}"'
        )
    with open(constants_py_path, "w") as f:
        f.write(constants_py)

    changelog_yaml = f"""- bump: patch\n  changes:\n    changed:\n    - Bump {country} to {version}\n"""
    # Write changelog_yaml to changelog.yaml
    with open("changelog_entry.yaml", "w") as f:
        f.write(changelog_yaml)
    # Run `make changelog`
    os.system("make changelog")

    # Commit the change and push to a branch
    branch_name = f"bump-{country}-to-{version}"
    os.system(f"git checkout -b {branch_name}")
    os.system(f"git add {setup_py_path}")
    os.system(f"git add {constants_py_path}")
    os.system(f"git commit -m 'Bump {country} to {version}'")
    os.system(f"git push origin {branch_name}")
    # Open a PR
    os.system(
        f"gh pr create --title 'Bump {country} to {version}' --body 'Bump {country} to {version}' --base main --head {branch_name}"
    )


if __name__ == "__main__":
    main()
