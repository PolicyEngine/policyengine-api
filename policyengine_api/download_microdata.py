from policyengine_us_data import EnhancedCPS_2024, CPS_2024
from policyengine_uk_data import EnhancedFRS_2022_23

DATASETS = [EnhancedCPS_2024, CPS_2024, EnhancedFRS_2022_23]


def download_microdata():
    for dataset in DATASETS:
        dataset = dataset()
        if not dataset.exists:
            dataset.download()


if __name__ == "__main__":
    download_microdata()
