import json
import subprocess
import sys

import pytest

from policyengine_api.constants import (
    COUNTRY_PACKAGE_VERSIONS,
    POLICYENGINE_CORE_VERSION,
    POLICYENGINE_VERSION,
    REGION_PREFIXES,
    RUNTIME_CACHE_SCHEMA_VERSIONS,
    RUNTIME_CACHE_VERSION_LENGTH,
    UK_REGION_TYPES,
    US_REGION_TYPES,
    _bundle_dataset_display_label,
    _load_policyengine_bundle,
    _normalize_distribution_name,
    _resolve_distribution_version,
    get_economy_impact_cache_version,
    get_py_manifest,
)

# Prepended to a subprocess script: any import of .py (the ``policyengine``
# package) after this raises.
BLOCK_POLICYENGINE_IMPORTS = """
import importlib.abc
import json
import sys


class BlockPolicyEngineImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "policyengine" or fullname.startswith("policyengine."):
            raise AssertionError(f"Unexpected import: {fullname}")
        return None


sys.meta_path.insert(0, BlockPolicyEngineImports())
"""


class TestBundleDatasetDisplayLabels:
    @pytest.mark.parametrize(
        ("dataset_name", "expected_label"),
        [
            ("populace_us_2024", "Microcosm"),
            ("microcosm_uk_2024_25", "Microcosm"),
            ("microcosm_uk_2024_25_dense", "Microcosm"),
            ("enhanced_frs_2024_25", "Enhanced FRS"),
            ("future_dataset", "Certified dataset"),
            (None, "Certified dataset"),
        ],
    )
    def test__uses_user_facing_dataset_family_name(self, dataset_name, expected_label):
        assert _bundle_dataset_display_label(dataset_name) == expected_label


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


class TestEconomyImpactCacheVersion:
    # Since its move to .py 4.x, the simulation API returned decile.relative
    # and the UK wealth_decile.relative as percentages (x100) instead of
    # fractions (PolicyEngine/policyengine-sim-api#827). Economy results
    # cached under schema version 3 can hold those values, and the cache key
    # does not change when the simulation API's code does, so version 4 makes
    # every economy cache lookup miss them and recompute.
    def test__economy_impact_schema_version_is_4(self):
        assert RUNTIME_CACHE_SCHEMA_VERSIONS["economy_impact"] == 4

    @pytest.mark.parametrize("country_id", ["us", "uk"])
    def test__economy_impact_cache_version_carries_schema_version_4(self, country_id):
        cache_version = get_economy_impact_cache_version(country_id)

        assert cache_version.startswith("e4")
        assert len(cache_version) == RUNTIME_CACHE_VERSION_LENGTH


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
        code = (
            BLOCK_POLICYENGINE_IMPORTS
            + """
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
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == self._expected_bundle_versions()

    def test__uk_area_names_load_without_importing_policyengine(self):
        """.py's packaged area lists are read in file order, without importing .py.

        Importing any .py module builds .py's country models, which takes
        several seconds and requests release manifests over the network.
        """
        code = (
            BLOCK_POLICYENGINE_IMPORTS
            + """
from policyengine_api.constants import get_py_uk_area_names  # noqa: E402

print(
    json.dumps(
        {
            area_type: get_py_uk_area_names(area_type)
            for area_type in ("constituency", "local_authority")
        }
    )
)
"""
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            text=True,
            capture_output=True,
            check=False,
        )

        from policyengine.countries.uk.regions import build_uk_region_registry

        registry = build_uk_region_registry(
            include_constituencies=True, include_local_authorities=True
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {
            area_type: [region.label for region in registry.get_by_type(area_type)]
            for area_type in ("constituency", "local_authority")
        }

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

        with pytest.raises(TypeError, match="must be a JSON object"):
            _load_policyengine_bundle()

    def test__uses_policyengine_bundle_versions_for_us_uk_and_core(self):
        expected_versions = self._expected_bundle_versions()
        assert expected_versions["policyengine"] == POLICYENGINE_VERSION
        assert expected_versions["core"] == POLICYENGINE_CORE_VERSION
        assert COUNTRY_PACKAGE_VERSIONS["us"] == expected_versions["us"]
        assert COUNTRY_PACKAGE_VERSIONS["uk"] == expected_versions["uk"]
