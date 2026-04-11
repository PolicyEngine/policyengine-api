ENHANCED_FRS = (
    "hf://policyengine/policyengine-uk-data-private/"
    "enhanced_frs_2023_24.h5@1.40.3"
)
FRS = "hf://policyengine/policyengine-uk-data-private/frs_2023_24.h5@1.40.3"

ENHANCED_CPS = "hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5@1.77.0"
CPS = "hf://policyengine/policyengine-us-data/cps_2023.h5@1.77.0"
POOLED_CPS = "hf://policyengine/policyengine-us-data/pooled_3_year_cps_2023.h5@1.77.0"

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
