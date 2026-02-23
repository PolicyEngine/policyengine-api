import pytest
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd
from pydantic import ValidationError

from policyengine_api.endpoints.economy.compare import (
    UKConstituencyBreakdownByConstituency,
    UKConstituencyBreakdown,
    UKLocalAuthorityBreakdownByLA,
    UKLocalAuthorityBreakdown,
    uk_constituency_breakdown,
    uk_local_authority_breakdown,
    intra_decile_impact,
    intra_wealth_decile_impact,
)


class TestUKLocalAuthorityBreakdownByLA:
    """Tests for the UKLocalAuthorityBreakdownByLA Pydantic model."""

    def test__given_valid_data__creates_instance(self):
        breakdown = UKLocalAuthorityBreakdownByLA(
            average_household_income_change=100.50,
            relative_household_income_change=0.05,
            x=10,
            y=20,
        )
        assert breakdown.average_household_income_change == 100.50
        assert breakdown.relative_household_income_change == 0.05
        assert breakdown.x == 10
        assert breakdown.y == 20

    def test__given_negative_income_change__creates_instance(self):
        breakdown = UKLocalAuthorityBreakdownByLA(
            average_household_income_change=-500.0,
            relative_household_income_change=-0.03,
            x=5,
            y=-10,
        )
        assert breakdown.average_household_income_change == -500.0
        assert breakdown.relative_household_income_change == -0.03

    def test__given_zero_values__creates_instance(self):
        breakdown = UKLocalAuthorityBreakdownByLA(
            average_household_income_change=0.0,
            relative_household_income_change=0.0,
            x=0,
            y=0,
        )
        assert breakdown.average_household_income_change == 0.0
        assert breakdown.relative_household_income_change == 0.0

    def test__given_missing_field__raises_validation_error(self):
        with pytest.raises(ValidationError):
            UKLocalAuthorityBreakdownByLA(
                average_household_income_change=100.0,
                # Missing relative_household_income_change
                x=10,
                y=20,
            )


class TestUKLocalAuthorityBreakdown:
    """Tests for the UKLocalAuthorityBreakdown Pydantic model."""

    def test__given_valid_data__creates_instance(self):
        breakdown = UKLocalAuthorityBreakdown(
            by_local_authority={
                "Hartlepool": UKLocalAuthorityBreakdownByLA(
                    average_household_income_change=100.0,
                    relative_household_income_change=0.02,
                    x=8,
                    y=19,
                )
            },
            outcomes_by_region={
                "uk": {"Gain more than 5%": 1, "No change": 0},
                "england": {"Gain more than 5%": 1, "No change": 0},
            },
        )
        assert "Hartlepool" in breakdown.by_local_authority
        assert "uk" in breakdown.outcomes_by_region

    def test__given_empty_by_local_authority__creates_instance(self):
        breakdown = UKLocalAuthorityBreakdown(
            by_local_authority={},
            outcomes_by_region={
                "uk": {"No change": 0},
            },
        )
        assert len(breakdown.by_local_authority) == 0

    def test__model_dump_returns_dict(self):
        breakdown = UKLocalAuthorityBreakdown(
            by_local_authority={
                "Leicester": UKLocalAuthorityBreakdownByLA(
                    average_household_income_change=50.0,
                    relative_household_income_change=0.01,
                    x=8,
                    y=8,
                )
            },
            outcomes_by_region={"uk": {"No change": 1}},
        )
        result = breakdown.model_dump()
        assert isinstance(result, dict)
        assert "by_local_authority" in result
        assert "outcomes_by_region" in result


class TestUKLocalAuthorityBreakdownFunction:
    """Tests for the uk_local_authority_breakdown function."""

    def test__given_non_uk_country__returns_none(self):
        result = uk_local_authority_breakdown({}, {}, "us")
        assert result is None

    def test__given_non_uk_country_canada__returns_none(self):
        result = uk_local_authority_breakdown({}, {}, "ca")
        assert result is None

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__given_uk_country__returns_breakdown(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        # Setup mocks
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        # Create mock weights - 3 local authorities, 10 households
        mock_weights = np.ones((3, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        # Create mock local authority names DataFrame
        mock_la_df = pd.DataFrame(
            {
                "code": ["E06000001", "S12000033", "W06000001"],
                "name": ["Hartlepool", "Aberdeen City", "Isle of Anglesey"],
                "x": [8.0, 5.0, 3.0],
                "y": [19.0, 10.0, 15.0],
            }
        )
        mock_read_csv.return_value = mock_la_df

        # Create baseline and reform data
        baseline = {"household_net_income": np.array([1000.0] * 10)}
        reform = {"household_net_income": np.array([1050.0] * 10)}

        result = uk_local_authority_breakdown(baseline, reform, "uk")

        assert result is not None
        assert isinstance(result, UKLocalAuthorityBreakdown)
        assert "Hartlepool" in result.by_local_authority
        assert "Aberdeen City" in result.by_local_authority
        assert "Isle of Anglesey" in result.by_local_authority

    def test__region_categorization_by_code_prefix(self):
        """Test that region categorization logic correctly identifies UK nations by code prefix."""
        # This is a unit test for the region categorization logic
        # We test the logic directly rather than through the full function

        test_cases = [
            ("E06000001", ["uk", "england"]),  # English LA
            ("S12000033", ["uk", "scotland"]),  # Scottish LA
            ("W06000001", ["uk", "wales"]),  # Welsh LA
            ("N09000001", ["uk", "northern_ireland"]),  # NI LA
        ]

        for code, expected_regions in test_cases:
            regions = ["uk"]
            if code.startswith("E"):
                regions.append("england")
            elif code.startswith("S"):
                regions.append("scotland")
            elif code.startswith("W"):
                regions.append("wales")
            elif code.startswith("N"):
                regions.append("northern_ireland")

            assert regions == expected_regions, f"Failed for code {code}"

    def test__outcome_bucket_categorization_logic(self):
        """Test that outcome bucket categorization logic is correct."""
        # Thresholds: > 0.05 (5%), > 0.001 (0.1%), > -0.001, > -0.05
        test_cases = [
            (0.10, "Gain more than 5%"),  # 10% gain
            (0.06, "Gain more than 5%"),  # 6% gain
            (0.051, "Gain more than 5%"),  # Just over 5%
            (0.05, "Gain less than 5%"),  # Exactly 5% gain (not > 5%)
            (0.03, "Gain less than 5%"),  # 3% gain
            (0.002, "Gain less than 5%"),  # 0.2% gain (> 0.001)
            (0.001, "No change"),  # Exactly 0.1% - not > 0.001
            (0.0005, "No change"),  # 0.05% gain (within tolerance)
            (0.0, "No change"),  # No change
            (-0.0005, "No change"),  # 0.05% loss (> -0.001)
            (-0.001, "Lose less than 5%"),  # Exactly -0.1% (not > -0.001)
            (-0.002, "Lose less than 5%"),  # 0.2% loss
            (-0.03, "Lose less than 5%"),  # 3% loss
            (-0.049, "Lose less than 5%"),  # Just under 5% loss (> -0.05)
            (-0.05, "Lose more than 5%"),  # Exactly 5% loss (not > -0.05)
            (-0.051, "Lose more than 5%"),  # Just over 5% loss
            (-0.06, "Lose more than 5%"),  # 6% loss
            (-0.10, "Lose more than 5%"),  # 10% loss
        ]

        for percent_change, expected_bucket in test_cases:
            if percent_change > 0.05:
                bucket = "Gain more than 5%"
            elif percent_change > 1e-3:
                bucket = "Gain less than 5%"
            elif percent_change > -1e-3:
                bucket = "No change"
            elif percent_change > -0.05:
                bucket = "Lose less than 5%"
            else:
                bucket = "Lose more than 5%"

            assert (
                bucket == expected_bucket
            ), f"Failed for {percent_change}: expected {expected_bucket}, got {bucket}"

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__outcome_buckets_are_correct(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        mock_weights = np.ones((1, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        mock_la_df = pd.DataFrame(
            {
                "code": ["E06000001"],
                "name": ["Hartlepool"],
                "x": [8.0],
                "y": [19.0],
            }
        )
        mock_read_csv.return_value = mock_la_df

        baseline = {"household_net_income": np.array([1000.0] * 10)}
        # 10% gain - should be "Gain more than 5%"
        reform = {"household_net_income": np.array([1100.0] * 10)}

        result = uk_local_authority_breakdown(baseline, reform, "uk")

        assert result.outcomes_by_region["uk"]["Gain more than 5%"] == 1
        assert result.outcomes_by_region["uk"]["Gain less than 5%"] == 0

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__downloads_from_correct_repos(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        mock_weights = np.ones((1, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        mock_la_df = pd.DataFrame(
            {
                "code": ["E06000001"],
                "name": ["Test"],
                "x": [0.0],
                "y": [0.0],
            }
        )
        mock_read_csv.return_value = mock_la_df

        baseline = {"household_net_income": np.array([1000.0] * 10)}
        reform = {"household_net_income": np.array([1000.0] * 10)}

        uk_local_authority_breakdown(baseline, reform, "uk")

        # Verify correct repos are used
        calls = mock_download.call_args_list
        assert (
            calls[0][1]["repo"] == "policyengine/policyengine-uk-data-private"
        )
        assert calls[0][1]["repo_filename"] == "local_authority_weights.h5"
        assert (
            calls[1][1]["repo"] == "policyengine/policyengine-uk-data-public"
        )
        assert calls[1][1]["repo_filename"] == "local_authorities_2021.csv"

    def test__given_constituency_region__returns_none(self):
        """When simulating a constituency, local authority breakdown should not be computed."""
        result = uk_local_authority_breakdown(
            {}, {}, "uk", "constituency/Aldershot"
        )
        assert result is None

    def test__given_constituency_region_with_code__returns_none(self):
        """When simulating a constituency by code, local authority breakdown should not be computed."""
        result = uk_local_authority_breakdown(
            {}, {}, "uk", "constituency/E12345678"
        )
        assert result is None

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__given_specific_la_region__returns_only_that_la(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        """When simulating a specific local authority, only that LA should be returned."""
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        mock_weights = np.ones((3, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        mock_la_df = pd.DataFrame(
            {
                "code": ["E06000001", "S12000033", "W06000001"],
                "name": ["Hartlepool", "Aberdeen City", "Isle of Anglesey"],
                "x": [8.0, 5.0, 3.0],
                "y": [19.0, 10.0, 15.0],
            }
        )
        mock_read_csv.return_value = mock_la_df

        baseline = {"household_net_income": np.array([1000.0] * 10)}
        reform = {"household_net_income": np.array([1050.0] * 10)}

        result = uk_local_authority_breakdown(
            baseline, reform, "uk", "local_authority/Hartlepool"
        )

        assert result is not None
        assert len(result.by_local_authority) == 1
        assert "Hartlepool" in result.by_local_authority
        assert "Aberdeen City" not in result.by_local_authority
        assert "Isle of Anglesey" not in result.by_local_authority

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__given_country_scotland_region__returns_only_scottish_las(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        """When simulating country/scotland, only Scottish local authorities should be returned."""
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        mock_weights = np.ones((3, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        mock_la_df = pd.DataFrame(
            {
                "code": ["E06000001", "S12000033", "W06000001"],
                "name": ["Hartlepool", "Aberdeen City", "Isle of Anglesey"],
                "x": [8.0, 5.0, 3.0],
                "y": [19.0, 10.0, 15.0],
            }
        )
        mock_read_csv.return_value = mock_la_df

        baseline = {"household_net_income": np.array([1000.0] * 10)}
        reform = {"household_net_income": np.array([1050.0] * 10)}

        result = uk_local_authority_breakdown(
            baseline, reform, "uk", "country/scotland"
        )

        assert result is not None
        assert len(result.by_local_authority) == 1
        assert "Aberdeen City" in result.by_local_authority
        assert "Hartlepool" not in result.by_local_authority
        assert "Isle of Anglesey" not in result.by_local_authority

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__given_uk_region__returns_all_las(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        """When simulating uk-wide, all local authorities should be returned."""
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        mock_weights = np.ones((3, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        mock_la_df = pd.DataFrame(
            {
                "code": ["E06000001", "S12000033", "W06000001"],
                "name": ["Hartlepool", "Aberdeen City", "Isle of Anglesey"],
                "x": [8.0, 5.0, 3.0],
                "y": [19.0, 10.0, 15.0],
            }
        )
        mock_read_csv.return_value = mock_la_df

        baseline = {"household_net_income": np.array([1000.0] * 10)}
        reform = {"household_net_income": np.array([1050.0] * 10)}

        result = uk_local_authority_breakdown(baseline, reform, "uk", "uk")

        assert result is not None
        assert len(result.by_local_authority) == 3
        assert "Hartlepool" in result.by_local_authority
        assert "Aberdeen City" in result.by_local_authority
        assert "Isle of Anglesey" in result.by_local_authority

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__given_no_region__returns_all_las(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        """When no region specified (None), all local authorities should be returned."""
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        mock_weights = np.ones((3, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        mock_la_df = pd.DataFrame(
            {
                "code": ["E06000001", "S12000033", "W06000001"],
                "name": ["Hartlepool", "Aberdeen City", "Isle of Anglesey"],
                "x": [8.0, 5.0, 3.0],
                "y": [19.0, 10.0, 15.0],
            }
        )
        mock_read_csv.return_value = mock_la_df

        baseline = {"household_net_income": np.array([1000.0] * 10)}
        reform = {"household_net_income": np.array([1050.0] * 10)}

        result = uk_local_authority_breakdown(baseline, reform, "uk", None)

        assert result is not None
        assert len(result.by_local_authority) == 3


class TestUKConstituencyBreakdownModels:
    """Tests for the existing UK constituency breakdown models (for completeness)."""

    def test__constituency_breakdown_by_constituency_creates_instance(self):
        breakdown = UKConstituencyBreakdownByConstituency(
            average_household_income_change=200.0,
            relative_household_income_change=0.04,
            x=56,
            y=-40,
        )
        assert breakdown.average_household_income_change == 200.0
        assert breakdown.x == 56

    def test__constituency_breakdown_creates_instance(self):
        breakdown = UKConstituencyBreakdown(
            by_constituency={
                "Aldershot": UKConstituencyBreakdownByConstituency(
                    average_household_income_change=150.0,
                    relative_household_income_change=0.03,
                    x=56,
                    y=-40,
                )
            },
            outcomes_by_region={"uk": {"No change": 1}},
        )
        assert "Aldershot" in breakdown.by_constituency


class TestUKConstituencyBreakdownFunction:
    """Tests for the uk_constituency_breakdown function."""

    def test__given_non_uk_country__returns_none(self):
        result = uk_constituency_breakdown({}, {}, "us")
        assert result is None

    def test__given_non_uk_country_nigeria__returns_none(self):
        result = uk_constituency_breakdown({}, {}, "ng")
        assert result is None

    def test__given_local_authority_region__returns_none(self):
        """When simulating a local authority, constituency breakdown should not be computed."""
        result = uk_constituency_breakdown(
            {}, {}, "uk", "local_authority/Leicester"
        )
        assert result is None

    def test__given_local_authority_region_with_code__returns_none(self):
        """When simulating a local authority by code, constituency breakdown should not be computed."""
        result = uk_constituency_breakdown(
            {}, {}, "uk", "local_authority/E06000016"
        )
        assert result is None

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__given_specific_constituency_region__returns_only_that_constituency(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        """When simulating a specific constituency, only that constituency should be returned."""
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        # Create mock weights - 3 constituencies, 10 households
        mock_weights = np.ones((3, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        # Create mock constituency names DataFrame
        mock_const_df = pd.DataFrame(
            {
                "code": ["E12345678", "S12345678", "W12345678"],
                "name": ["Aldershot", "Edinburgh East", "Cardiff South"],
                "x": [10.0, 5.0, 3.0],
                "y": [20.0, 15.0, 12.0],
            }
        )
        mock_read_csv.return_value = mock_const_df

        baseline = {"household_net_income": np.array([1000.0] * 10)}
        reform = {"household_net_income": np.array([1050.0] * 10)}

        result = uk_constituency_breakdown(
            baseline, reform, "uk", "constituency/Aldershot"
        )

        assert result is not None
        assert len(result.by_constituency) == 1
        assert "Aldershot" in result.by_constituency
        assert "Edinburgh East" not in result.by_constituency
        assert "Cardiff South" not in result.by_constituency

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__given_country_scotland_region__returns_only_scottish_constituencies(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        """When simulating country/scotland, only Scottish constituencies should be returned."""
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        mock_weights = np.ones((3, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        mock_const_df = pd.DataFrame(
            {
                "code": ["E12345678", "S12345678", "W12345678"],
                "name": ["Aldershot", "Edinburgh East", "Cardiff South"],
                "x": [10.0, 5.0, 3.0],
                "y": [20.0, 15.0, 12.0],
            }
        )
        mock_read_csv.return_value = mock_const_df

        baseline = {"household_net_income": np.array([1000.0] * 10)}
        reform = {"household_net_income": np.array([1050.0] * 10)}

        result = uk_constituency_breakdown(
            baseline, reform, "uk", "country/scotland"
        )

        assert result is not None
        assert len(result.by_constituency) == 1
        assert "Edinburgh East" in result.by_constituency
        assert "Aldershot" not in result.by_constituency
        assert "Cardiff South" not in result.by_constituency

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__given_uk_region__returns_all_constituencies(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        """When simulating uk-wide, all constituencies should be returned."""
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        mock_weights = np.ones((3, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        mock_const_df = pd.DataFrame(
            {
                "code": ["E12345678", "S12345678", "W12345678"],
                "name": ["Aldershot", "Edinburgh East", "Cardiff South"],
                "x": [10.0, 5.0, 3.0],
                "y": [20.0, 15.0, 12.0],
            }
        )
        mock_read_csv.return_value = mock_const_df

        baseline = {"household_net_income": np.array([1000.0] * 10)}
        reform = {"household_net_income": np.array([1050.0] * 10)}

        result = uk_constituency_breakdown(baseline, reform, "uk", "uk")

        assert result is not None
        assert len(result.by_constituency) == 3
        assert "Aldershot" in result.by_constituency
        assert "Edinburgh East" in result.by_constituency
        assert "Cardiff South" in result.by_constituency

    @patch(
        "policyengine_api.endpoints.economy.compare.download_huggingface_dataset"
    )
    @patch("policyengine_api.endpoints.economy.compare.h5py.File")
    @patch("policyengine_api.endpoints.economy.compare.pd.read_csv")
    def test__given_no_region__returns_all_constituencies(
        self, mock_read_csv, mock_h5py_file, mock_download
    ):
        """When no region specified (None), all constituencies should be returned."""
        mock_download.side_effect = [
            "/path/to/weights.h5",
            "/path/to/names.csv",
        ]

        mock_weights = np.ones((3, 10))
        mock_h5py_context = MagicMock()
        mock_h5py_context.__enter__ = MagicMock(
            return_value={"2025": mock_weights}
        )
        mock_h5py_context.__exit__ = MagicMock(return_value=False)
        mock_h5py_file.return_value = mock_h5py_context

        mock_const_df = pd.DataFrame(
            {
                "code": ["E12345678", "S12345678", "W12345678"],
                "name": ["Aldershot", "Edinburgh East", "Cardiff South"],
                "x": [10.0, 5.0, 3.0],
                "y": [20.0, 15.0, 12.0],
            }
        )
        mock_read_csv.return_value = mock_const_df

        baseline = {"household_net_income": np.array([1000.0] * 10)}
        reform = {"household_net_income": np.array([1050.0] * 10)}

        result = uk_constituency_breakdown(baseline, reform, "uk", None)

        assert result is not None
        assert len(result.by_constituency) == 3


def _make_economy(
    incomes,
    deciles,
    weights=None,
    people=None,
    decile_key="household_income_decile",
):
    """Helper to build baseline/reform dicts for intra_decile tests."""
    n = len(incomes)
    return {
        "household_net_income": np.array(incomes, dtype=float),
        "household_weight": np.array(weights if weights else [1.0] * n),
        "household_count_people": np.array(people if people else [1.0] * n),
        decile_key: np.array(deciles, dtype=float),
    }


class TestIntraDecileImpact:
    """Tests for the intra_decile_impact function — verifying correct
    percentage change calculation and bucket assignment."""

    def test__5pct_gain_classified_below_5pct(self):
        """A uniform 5% income gain must NOT land in 'Gain more than 5%'.

        This is the regression test for the double-counting bug where
        income_change was 2x the true value, pushing 5% gains into the
        >5% bucket.
        """
        # 10 households, one per decile, all gain exactly 5%
        baseline = _make_economy(
            incomes=[1000.0] * 10,
            deciles=list(range(1, 11)),
        )
        reform = _make_economy(
            incomes=[1050.0] * 10,
            deciles=list(range(1, 11)),
        )
        result = intra_decile_impact(baseline, reform)

        # Every decile should have 0% in "Gain more than 5%"
        for pct in result["deciles"]["Gain more than 5%"]:
            assert (
                pct == 0.0
            ), f"5% gain incorrectly classified as >5% (got {pct})"
        # Every decile should have 100% in "Gain less than 5%"
        for pct in result["deciles"]["Gain less than 5%"]:
            assert pct == 1.0, f"5% gain not classified as <5% (got {pct})"

    def test__10pct_gain_classified_above_5pct(self):
        """A 10% gain should be in 'Gain more than 5%'."""
        baseline = _make_economy(
            incomes=[1000.0] * 10,
            deciles=list(range(1, 11)),
        )
        reform = _make_economy(
            incomes=[1100.0] * 10,
            deciles=list(range(1, 11)),
        )
        result = intra_decile_impact(baseline, reform)

        for pct in result["deciles"]["Gain more than 5%"]:
            assert pct == 1.0

    def test__3pct_loss_classified_below_5pct(self):
        """A 3% loss should be in 'Lose less than 5%'."""
        baseline = _make_economy(
            incomes=[1000.0] * 10,
            deciles=list(range(1, 11)),
        )
        reform = _make_economy(
            incomes=[970.0] * 10,
            deciles=list(range(1, 11)),
        )
        result = intra_decile_impact(baseline, reform)

        for pct in result["deciles"]["Lose less than 5%"]:
            assert pct == 1.0
        for pct in result["deciles"]["Lose more than 5%"]:
            assert pct == 0.0

    def test__no_change_classified_correctly(self):
        """Zero change should land in 'No change'."""
        baseline = _make_economy(
            incomes=[1000.0] * 10,
            deciles=list(range(1, 11)),
        )
        reform = _make_economy(
            incomes=[1000.0] * 10,
            deciles=list(range(1, 11)),
        )
        result = intra_decile_impact(baseline, reform)

        for pct in result["deciles"]["No change"]:
            assert pct == 1.0

    def test__near_zero_baseline_no_division_error(self):
        """Households with near-zero baseline income should not cause
        division errors — the floor of 1 handles this."""
        baseline = _make_economy(
            incomes=[0.0] * 10,
            deciles=list(range(1, 11)),
        )
        reform = _make_economy(
            incomes=[100.0] * 10,
            deciles=list(range(1, 11)),
        )
        result = intra_decile_impact(baseline, reform)

        # Should not raise; all households gained income
        total = sum(result["all"][label] for label in result["all"])
        assert (
            abs(total - 1.0) < 1e-9
        ), f"Proportions should sum to 1, got {total}"

    def test__zero_baseline_uses_floor_of_one(self):
        """When baseline income is 0, the max(B, 1) floor means the
        effective denominator is 1. A $0 -> $100 change should give
        income_change = 100/1 = 100 (10000%), landing in >5%."""
        baseline = _make_economy(
            incomes=[0.0] * 10,
            deciles=list(range(1, 11)),
        )
        reform = _make_economy(
            incomes=[100.0] * 10,
            deciles=list(range(1, 11)),
        )
        result = intra_decile_impact(baseline, reform)

        # $100 gain on a floored baseline of $1 = 10000% change -> >5%
        for pct in result["deciles"]["Gain more than 5%"]:
            assert (
                pct == 1.0
            ), f"Zero baseline with $100 gain should be >5% (got {pct})"
        # No NaN or Inf in any bucket
        for label in result["all"]:
            assert not np.isnan(result["all"][label])
            assert not np.isinf(result["all"][label])

    def test__negative_baseline_handled(self):
        """Households with negative baseline income should be handled
        by the max(B, 1) floor without producing NaN or Inf."""
        baseline = _make_economy(
            incomes=[-500.0] * 10,
            deciles=list(range(1, 11)),
        )
        reform = _make_economy(
            incomes=[500.0] * 10,
            deciles=list(range(1, 11)),
        )
        result = intra_decile_impact(baseline, reform)

        for label in result["all"]:
            assert not np.isnan(result["all"][label])
            assert not np.isinf(result["all"][label])

    def test__percentage_change_is_not_doubled(self):
        """Direct arithmetic check: a 2% gain must produce income_change
        of 0.02, not 0.04. We verify via bucket assignment — 2% is well
        within the <5% bucket."""
        baseline = _make_economy(
            incomes=[50000.0] * 10,
            deciles=list(range(1, 11)),
        )
        reform = _make_economy(
            incomes=[51000.0] * 10,  # +2%
            deciles=list(range(1, 11)),
        )
        result = intra_decile_impact(baseline, reform)

        # 2% gain must be in "Gain less than 5%", not "Gain more than 5%"
        for pct in result["deciles"]["Gain more than 5%"]:
            assert pct == 0.0, "2% gain incorrectly classified as >5%"
        for pct in result["deciles"]["Gain less than 5%"]:
            assert pct == 1.0, "2% gain not classified as <5%"

    def test__all_field_averages_deciles(self):
        """The 'all' field should be the mean of the 10 decile values."""
        baseline = _make_economy(
            incomes=[1000.0] * 10,
            deciles=list(range(1, 11)),
        )
        reform = _make_economy(
            incomes=[1050.0] * 10,
            deciles=list(range(1, 11)),
        )
        result = intra_decile_impact(baseline, reform)

        for label in result["all"]:
            expected = sum(result["deciles"][label]) / 10
            assert abs(result["all"][label] - expected) < 1e-9


class TestIntraWealthDecileImpact:
    """Tests for intra_wealth_decile_impact — same formula, keyed by
    wealth decile instead of income decile."""

    def test__5pct_gain_classified_below_5pct(self):
        """Regression test: 5% gain must not be doubled into >5% bucket."""
        baseline = _make_economy(
            incomes=[1000.0] * 10,
            deciles=list(range(1, 11)),
            decile_key="household_wealth_decile",
        )
        reform = _make_economy(
            incomes=[1050.0] * 10,
            deciles=list(range(1, 11)),
            decile_key="household_wealth_decile",
        )

        result = intra_wealth_decile_impact(baseline, reform)

        for pct in result["deciles"]["Gain more than 5%"]:
            assert (
                pct == 0.0
            ), f"5% gain incorrectly classified as >5% in wealth decile (got {pct})"

    def test__2pct_gain_not_doubled(self):
        """A 2% gain must stay in the <5% bucket for wealth deciles too."""
        baseline = _make_economy(
            incomes=[50000.0] * 10,
            deciles=list(range(1, 11)),
            decile_key="household_wealth_decile",
        )
        reform = _make_economy(
            incomes=[51000.0] * 10,
            deciles=list(range(1, 11)),
            decile_key="household_wealth_decile",
        )

        result = intra_wealth_decile_impact(baseline, reform)

        for pct in result["deciles"]["Gain more than 5%"]:
            assert pct == 0.0, "2% gain incorrectly classified as >5%"
        for pct in result["deciles"]["Gain less than 5%"]:
            assert pct == 1.0, "2% gain not classified as <5%"
