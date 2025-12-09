import pytest

from policyengine_api.data.model_setup import get_dataset_version


class TestGetDatasetVersion:
    """Tests for the get_dataset_version function."""

    def test__given_us__returns_none(self):
        result = get_dataset_version("us")
        assert result is None

    def test__given_uk__returns_none(self):
        result = get_dataset_version("uk")
        assert result is None

    def test__given_invalid_country__raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            get_dataset_version("invalid")
        assert "Unknown country ID: invalid" in str(exc_info.value)

    def test__given_empty_string__raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            get_dataset_version("")
        assert "Unknown country ID:" in str(exc_info.value)

    def test__given_canada__raises_value_error(self):
        # Canada is a valid country in the API but doesn't have dataset versioning
        with pytest.raises(ValueError) as exc_info:
            get_dataset_version("ca")
        assert "Unknown country ID: ca" in str(exc_info.value)
