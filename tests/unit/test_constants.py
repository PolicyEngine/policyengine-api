import json
import subprocess
import sys

import pytest
from policyengine_api.constants import (
    COUNTRY_PACKAGE_VERSIONS,
    POLICYENGINE_CORE_VERSION,
    POLICYENGINE_VERSION,
    REGION_PREFIXES,
    UK_REGION_TYPES,
    US_REGION_TYPES,
    _load_policyengine_bundle,
    _normalize_distribution_name,
    _resolve_distribution_version,
    get_py_manifest,
)


class TestUKRegionTypes:
    """Tests for UK_REGION_TYPES constant."""

    def test__contains_national(self):
        assert "national" in UK_REGION_TYPES

    def test__contains_country(self):
        assert "country" in UK_REGION_TYPES

    def test__contains_constituency(self):
        assert "constituency" in UK_REGION_TYPES

    def test__contains_local_authority(self):
        assert "local_authority" in UK_REGION_TYPES

    def test__has_exactly_four_types(self):
        assert len(UK_REGION_TYPES) == 4


class TestUSRegionTypes:
    """Tests for US_REGION_TYPES constant."""

    def test__contains_national(self):
        assert "national" in US_REGION_TYPES

    def test__contains_state(self):
        assert "state" in US_REGION_TYPES

    def test__contains_place(self):
        assert "place" in US_REGION_TYPES

    def test__contains_congressional_district(self):
        assert "congressional_district" in US_REGION_TYPES

    def test__has_exactly_four_types(self):
        assert len(US_REGION_TYPES) == 4


class TestRegionPrefixes:
    """Tests for REGION_PREFIXES constant."""

    class TestUKPrefixes:
        """Tests for UK region prefixes."""

        def test__uk_key_exists(self):
            assert "uk" in REGION_PREFIXES

        def test__contains_country_prefix(self):
            assert "country/" in REGION_PREFIXES["uk"]

        def test__contains_constituency_prefix(self):
            assert "constituency/" in REGION_PREFIXES["uk"]

        def test__contains_local_authority_prefix(self):
            assert "local_authority/" in REGION_PREFIXES["uk"]

        def test__has_exactly_three_prefixes(self):
            assert len(REGION_PREFIXES["uk"]) == 3

    class TestUSPrefixes:
        """Tests for US region prefixes."""

        def test__us_key_exists(self):
            assert "us" in REGION_PREFIXES

        def test__contains_state_prefix(self):
            assert "state/" in REGION_PREFIXES["us"]

        def test__contains_place_prefix(self):
            assert "place/" in REGION_PREFIXES["us"]

        def test__contains_congressional_district_prefix(self):
            assert "congressional_district/" in REGION_PREFIXES["us"]

        def test__has_exactly_three_prefixes(self):
            assert len(REGION_PREFIXES["us"]) == 3


class TestDistributionVersionHelpers:
    def test__normalize_distribution_name(self):
        assert _normalize_distribution_name("policyengine_core") == (
            "policyengine-core"
        )
        assert _normalize_distribution_name("PolicyEngine-Core") == (
            "policyengine-core"
        )

    def test__resolve_distribution_version_prefers_first_available_name(self):
        dist_versions = {
            "policyengine-core": "3.23.6",
            "policyengine": "0.12.1",
        }

        assert (
            _resolve_distribution_version(
                dist_versions, "policyengine-core", "policyengine"
            )
            == "3.23.6"
        )

    def test__resolve_distribution_version_falls_back_to_default(self):
        assert (
            _resolve_distribution_version({}, "policyengine-core", "policyengine")
            == "0.0.0"
        )


class TestPolicyEngineBundleVersions:
    @staticmethod
    def _expected_bundle_versions() -> dict[str, str]:
        manifest = json.loads(get_py_manifest().read_text(encoding="utf-8"))
        packages = manifest["packages"]
        normalized_packages = {
            _normalize_distribution_name(package.get("name") or package_key): package
            for package_key, package in packages.items()
        }
        return {
            "policyengine": str(
                manifest.get("policyengine_version") or manifest.get("bundle_version")
            ),
            "core": str(normalized_packages["policyengine-core"]["version"]),
            "us": str(normalized_packages["policyengine-us"]["version"]),
            "uk": str(normalized_packages["policyengine-uk"]["version"]),
        }

    def test__get_py_manifest_returns_packaged_manifest_path(self):
        manifest_path = get_py_manifest()

        assert manifest_path.name == "manifest.json"
        assert manifest_path.exists()

    def test__constants_load_from_manifest_without_importing_policyengine(self):
        code = """
import importlib.abc
import json
import sys


class BlockPolicyEngineImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "policyengine" or fullname.startswith("policyengine."):
            raise AssertionError(f"Unexpected import: {fullname}")
        return None


sys.meta_path.insert(0, BlockPolicyEngineImports())

from policyengine_api.constants import (  # noqa: E402
    COUNTRY_PACKAGE_VERSIONS,
    POLICYENGINE_CORE_VERSION,
    POLICYENGINE_VERSION,
)

print(
    json.dumps(
        {
            "policyengine": POLICYENGINE_VERSION,
            "core": POLICYENGINE_CORE_VERSION,
            "us": COUNTRY_PACKAGE_VERSIONS["us"],
            "uk": COUNTRY_PACKAGE_VERSIONS["uk"],
        }
    )
)
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == self._expected_bundle_versions()

    def test__load_policyengine_bundle_rejects_missing_manifest(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            "policyengine_api.constants.get_py_manifest",
            lambda: tmp_path / "missing-manifest.json",
        )

        with pytest.raises(RuntimeError, match="Could not read PolicyEngine"):
            _load_policyengine_bundle()

    def test__load_policyengine_bundle_rejects_non_object_manifest(
        self, monkeypatch, tmp_path
    ):
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(
            "policyengine_api.constants.get_py_manifest",
            lambda: manifest_path,
        )

        with pytest.raises(RuntimeError, match="must be a JSON object"):
            _load_policyengine_bundle()

    def test__uses_policyengine_bundle_versions_for_us_uk_and_core(self):
        expected_versions = self._expected_bundle_versions()
        assert POLICYENGINE_VERSION == expected_versions["policyengine"]
        assert POLICYENGINE_CORE_VERSION == expected_versions["core"]
        assert COUNTRY_PACKAGE_VERSIONS["us"] == expected_versions["us"]
        assert COUNTRY_PACKAGE_VERSIONS["uk"] == expected_versions["uk"]
