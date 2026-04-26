from policyengine_api.libs.runtime_bundle import resolve_runtime_bundle


class TestResolveRuntimeBundle:
    def test_default_us_national_resolves_canonical_and_worker_dataset(self):
        bundle = resolve_runtime_bundle(
            country_id="us",
            region="us",
            dataset="default",
            requested_model_version="1.653.3",
        )

        assert bundle.worker_dataset_uri.startswith("gs://policyengine-us-data/")
        assert bundle.canonical_dataset_uri.startswith(
            "hf://policyengine/policyengine-us-data/"
        )
        assert bundle.data_version is not None
        assert bundle.model_version == "1.653.3"
        assert bundle.provenance_status == "managed"
        assert bundle.as_payload()["fingerprint"].startswith("sha256:")

    def test_default_us_district_keeps_region_specific_dataset(self):
        bundle = resolve_runtime_bundle(
            country_id="us",
            region="congressional_district/CA-37",
            dataset="default",
        )

        assert bundle.worker_dataset_uri.endswith("/districts/CA-37.h5")
        assert "/districts/CA-37.h5@" in bundle.canonical_dataset_uri

    def test_explicit_hf_uri_extracts_data_version(self):
        bundle = resolve_runtime_bundle(
            country_id="us",
            region="us",
            dataset="hf://policyengine/policyengine-us-data/cps_2023.h5@1.77.0",
        )

        assert bundle.data_version == "1.77.0"
        assert bundle.worker_dataset_uri == "gs://policyengine-us-data/cps_2023.h5"

    def test_passthrough_dataset_is_unmanaged_but_still_fingerprinted(self):
        bundle = resolve_runtime_bundle(
            country_id="us",
            region="us",
            dataset="national-with-breakdowns",
        )

        assert bundle.worker_dataset_uri == "national-with-breakdowns"
        assert bundle.canonical_dataset_uri is None
        assert bundle.provenance_status == "unmanaged"
        assert bundle.fingerprint.startswith("sha256:")
