from policyengine_api.data.model_setup import (
    CPS,
    ENHANCED_CPS,
    ENHANCED_FRS,
    FRS,
    POOLED_CPS,
    datasets,
)


class TestDatasets:
    def test__given_us_aliases__then_returns_versioned_public_hf_uris(self):
        assert datasets["us"] == {
            "enhanced_cps": ENHANCED_CPS,
            "cps": CPS,
            "pooled_cps": POOLED_CPS,
        }
        assert ENHANCED_CPS.endswith("@1.77.0")
        assert CPS.endswith("@1.77.0")
        assert POOLED_CPS.endswith("@1.77.0")

    def test__given_uk_aliases__then_returns_versioned_private_hf_uris(self):
        assert datasets["uk"] == {
            "enhanced_frs": ENHANCED_FRS,
            "frs": FRS,
        }
        assert ENHANCED_FRS.startswith("hf://policyengine/policyengine-uk-data-private/")
        assert FRS.startswith("hf://policyengine/policyengine-uk-data-private/")
        assert ENHANCED_FRS.endswith("@1.40.3")
        assert FRS.endswith("@1.40.3")

    def test__given_unknown_country__then_has_no_dataset_aliases(self):
        assert "ca" not in datasets
        assert "invalid" not in datasets
