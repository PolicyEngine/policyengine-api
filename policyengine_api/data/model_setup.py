ENHANCED_FRS = "hf://policyengine/policyengine-uk-data/enhanced_frs_2023_24.h5"
FRS = "hf://policyengine/policyengine-uk-data/frs_2023_24.h5"

ENHANCED_CPS = "hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5"
CPS = "hf://policyengine/policyengine-us-data/cps_2023.h5"
POOLED_CPS = "hf://policyengine/policyengine-us-data/pooled_3_year_cps_2023.h5"

datasets = {
    "uk": {
        "enhanced_frs": ENHANCED_FRS,
        "frs": FRS,
    },
    "us": {
        "enhanced_cps": ENHANCED_CPS,
        "cps": CPS,
        "pooled_cps": POOLED_CPS,
    },
}


def get_dataset_version(country_id: str) -> str | None:
    """
    Get the dataset version for the specified country. If PolicyEngine does not
    publish data for the country, raise a ValueError.

    By returning None for all valid countries, we allow policyengine.py to use
    whatever default dataset version it has available, without imposing version
    validation constraints from the API layer.
    """
    match country_id:
        case "uk":
            return None
        case "us":
            return None
        case _:
            raise ValueError(f"Unknown country ID: {country_id}")


for dataset in datasets["uk"]:
    datasets["uk"][dataset] = f"{datasets['uk'][dataset]}@{get_dataset_version('uk')}"

for dataset in datasets["us"]:
    datasets["us"][dataset] = f"{datasets['us'][dataset]}@{get_dataset_version('us')}"
