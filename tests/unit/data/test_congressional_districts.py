import pytest
from pydantic import ValidationError

from policyengine_api.data.congressional_districts import (
    CongressionalDistrictMetadataItem,
    CONGRESSIONAL_DISTRICTS,
    STATE_CODE_TO_NAME,
    AT_LARGE_STATES,
    build_congressional_district_metadata,
    get_valid_state_codes,
    get_valid_congressional_districts,
)


class TestCongressionalDistrictMetadataItem:
    """Tests for the CongressionalDistrictMetadataItem Pydantic model."""

    def test__given_valid_state_code_and_number__creates_item(self):
        item = CongressionalDistrictMetadataItem(state_code="CA", number=37)
        assert item.state_code == "CA"
        assert item.number == 37

    def test__given_lowercase_state_code__raises_validation_error(self):
        with pytest.raises(ValidationError):
            CongressionalDistrictMetadataItem(state_code="ca", number=1)

    def test__given_single_letter_state_code__raises_validation_error(self):
        with pytest.raises(ValidationError):
            CongressionalDistrictMetadataItem(state_code="C", number=1)

    def test__given_three_letter_state_code__raises_validation_error(self):
        with pytest.raises(ValidationError):
            CongressionalDistrictMetadataItem(state_code="CAL", number=1)

    def test__given_zero_district_number__raises_validation_error(self):
        with pytest.raises(ValidationError):
            CongressionalDistrictMetadataItem(state_code="CA", number=0)

    def test__given_negative_district_number__raises_validation_error(self):
        with pytest.raises(ValidationError):
            CongressionalDistrictMetadataItem(state_code="CA", number=-1)


class TestStateCodeToName:
    """Tests for the STATE_CODE_TO_NAME mapping."""

    def test__contains_50_states_plus_dc(self):
        assert len(STATE_CODE_TO_NAME) == 51

    def test__contains_all_state_codes_uppercase(self):
        for code in STATE_CODE_TO_NAME.keys():
            assert code == code.upper()
            assert len(code) == 2

    def test__contains_dc(self):
        assert "DC" in STATE_CODE_TO_NAME
        assert STATE_CODE_TO_NAME["DC"] == "District of Columbia"

    def test__contains_california(self):
        assert "CA" in STATE_CODE_TO_NAME
        assert STATE_CODE_TO_NAME["CA"] == "California"


class TestCongressionalDistricts:
    """Tests for the CONGRESSIONAL_DISTRICTS list."""

    def test__contains_436_districts(self):
        # 435 voting districts + 1 DC non-voting
        assert len(CONGRESSIONAL_DISTRICTS) == 436

    def test__all_items_are_valid_metadata_items(self):
        for district in CONGRESSIONAL_DISTRICTS:
            assert isinstance(district, CongressionalDistrictMetadataItem)

    def test__all_state_codes_are_in_state_code_to_name(self):
        for district in CONGRESSIONAL_DISTRICTS:
            assert district.state_code in STATE_CODE_TO_NAME

    def test__california_has_52_districts(self):
        ca_districts = [
            d for d in CONGRESSIONAL_DISTRICTS if d.state_code == "CA"
        ]
        assert len(ca_districts) == 52

    def test__texas_has_38_districts(self):
        tx_districts = [
            d for d in CONGRESSIONAL_DISTRICTS if d.state_code == "TX"
        ]
        assert len(tx_districts) == 38

    def test__at_large_states_have_1_district(self):
        # States with only 1 at-large representative (excluding DC which is special)
        at_large_states = [s for s in AT_LARGE_STATES if s != "DC"]
        for state_code in at_large_states:
            state_districts = [
                d
                for d in CONGRESSIONAL_DISTRICTS
                if d.state_code == state_code
            ]
            assert len(state_districts) == 1
            assert state_districts[0].number == 1

    def test__dc_has_1_district(self):
        dc_districts = [
            d for d in CONGRESSIONAL_DISTRICTS if d.state_code == "DC"
        ]
        assert len(dc_districts) == 1
        assert dc_districts[0].number == 1

    def test__dc_comes_after_delaware(self):
        # Find indices
        de_indices = [
            i
            for i, d in enumerate(CONGRESSIONAL_DISTRICTS)
            if d.state_code == "DE"
        ]
        dc_indices = [
            i
            for i, d in enumerate(CONGRESSIONAL_DISTRICTS)
            if d.state_code == "DC"
        ]
        # DC should come after all DE districts
        assert min(dc_indices) > max(de_indices)


class TestBuildCongressionalDistrictMetadata:
    """Tests for the build_congressional_district_metadata function."""

    def test__returns_list_of_436_items(self):
        metadata = build_congressional_district_metadata()
        assert len(metadata) == 436

    def test__each_item_has_required_keys(self):
        metadata = build_congressional_district_metadata()
        for item in metadata:
            assert "name" in item
            assert "label" in item
            assert "type" in item
            assert "state_abbreviation" in item
            assert "state_name" in item

    def test__name_has_correct_format(self):
        metadata = build_congressional_district_metadata()
        # Check first California district
        ca_01 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-01"
        )
        assert ca_01 is not None

    def test__label_has_correct_format(self):
        metadata = build_congressional_district_metadata()
        ca_01 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-01"
        )
        assert ca_01["label"] == "California's 1st congressional district"

    def test__state_abbreviation_is_uppercase(self):
        metadata = build_congressional_district_metadata()
        for item in metadata:
            assert item["state_abbreviation"] == item["state_abbreviation"].upper()
            assert len(item["state_abbreviation"]) == 2

    def test__state_name_matches_abbreviation(self):
        metadata = build_congressional_district_metadata()
        ca_01 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-01"
        )
        assert ca_01["state_abbreviation"] == "CA"
        assert ca_01["state_name"] == "California"

    def test__dc_state_fields(self):
        metadata = build_congressional_district_metadata()
        dc_01 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/DC-01"
        )
        assert dc_01["state_abbreviation"] == "DC"
        assert dc_01["state_name"] == "District of Columbia"

    def test__type_is_congressional_district(self):
        metadata = build_congressional_district_metadata()
        for item in metadata:
            assert item["type"] == "congressional_district"

    def test__ordinal_suffixes_are_correct(self):
        metadata = build_congressional_district_metadata()

        # Find specific districts to test ordinal suffixes
        ca_01 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-01"
        )
        ca_02 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-02"
        )
        ca_03 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-03"
        )
        ca_11 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-11"
        )
        ca_12 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-12"
        )
        ca_21 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-21"
        )
        ca_22 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-22"
        )

        assert "1st" in ca_01["label"]
        assert "2nd" in ca_02["label"]
        assert "3rd" in ca_03["label"]
        assert "11th" in ca_11["label"]
        assert "12th" in ca_12["label"]
        assert "21st" in ca_21["label"]
        assert "22nd" in ca_22["label"]

    def test__district_numbers_have_leading_zeros(self):
        metadata = build_congressional_district_metadata()
        # Single digit districts should have leading zero
        ca_01 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-01"
        )
        assert ca_01["name"] == "congressional_district/CA-01"

        # Double digit districts should not have leading zero
        ca_37 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/CA-37"
        )
        assert ca_37["name"] == "congressional_district/CA-37"

    def test__at_large_states_have_at_large_label(self):
        metadata = build_congressional_district_metadata()
        # All at-large states should have "at-large" in label
        for state_code in AT_LARGE_STATES:
            district = next(
                item
                for item in metadata
                if item["name"]
                == f"congressional_district/{state_code}-01"
            )
            assert (
                "at-large congressional district" in district["label"]
            ), f"{state_code} should have at-large label"

    def test__alaska_at_large_label(self):
        metadata = build_congressional_district_metadata()
        ak_01 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/AK-01"
        )
        assert (
            ak_01["label"] == "Alaska's at-large congressional district"
        )

    def test__wyoming_at_large_label(self):
        metadata = build_congressional_district_metadata()
        wy_01 = next(
            item
            for item in metadata
            if item["name"] == "congressional_district/WY-01"
        )
        assert (
            wy_01["label"] == "Wyoming's at-large congressional district"
        )


class TestGetValidStateCodes:
    """Tests for the get_valid_state_codes function."""

    def test__returns_set_of_51_codes(self):
        codes = get_valid_state_codes()
        assert len(codes) == 51

    def test__all_codes_are_lowercase(self):
        codes = get_valid_state_codes()
        for code in codes:
            assert code == code.lower()

    def test__contains_california(self):
        codes = get_valid_state_codes()
        assert "ca" in codes

    def test__contains_dc(self):
        codes = get_valid_state_codes()
        assert "dc" in codes

    def test__does_not_contain_invalid_codes(self):
        codes = get_valid_state_codes()
        assert "xx" not in codes
        assert "mb" not in codes  # Manitoba (Canadian province)


class TestGetValidCongressionalDistricts:
    """Tests for the get_valid_congressional_districts function."""

    def test__returns_set_of_436_districts(self):
        districts = get_valid_congressional_districts()
        assert len(districts) == 436

    def test__all_districts_are_lowercase(self):
        districts = get_valid_congressional_districts()
        for district in districts:
            assert district == district.lower()

    def test__contains_california_37(self):
        districts = get_valid_congressional_districts()
        assert "ca-37" in districts

    def test__contains_dc_01(self):
        districts = get_valid_congressional_districts()
        assert "dc-01" in districts

    def test__single_digit_districts_have_leading_zero(self):
        districts = get_valid_congressional_districts()
        assert "ca-01" in districts
        assert "ca-1" not in districts

    def test__does_not_contain_invalid_districts(self):
        districts = get_valid_congressional_districts()
        assert "ca-99" not in districts
        assert "xx-01" not in districts
        assert "cruft" not in districts
