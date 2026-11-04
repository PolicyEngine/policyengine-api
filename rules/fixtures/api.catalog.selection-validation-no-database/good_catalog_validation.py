"""Proof fixture: version validation with no database imports. The rule accepts it."""

from packaging.version import Version


def validate_policyengine_version(value: str) -> str:
    """Return a canonical version string."""
    if str(Version(value)) != value:
        msg = "policyengine_version must be a canonical version"
        raise ValueError(msg)
    return value
