INSERT OR REPLACE INTO household (id, country_id, label, api_version, household_json, household_hash)
VALUES (
	-3,
	"uk",
	"Sample dataset - duplicate of UK household #12408 in live database",
	"0.10.0",
	'{
        "benunits": {
            "benunit": {
                "members": [
                    "adult_1"
                ]
            }
        },
        "households": {
            "household": {
                "BRMA": {
                    "2023": "ASHFORD"
                },
                "full_rate_vat_consumption": {
                    "2023": 0.0
                },
                "household_benefits": {
                    "2023": null
                },
                "household_net_income": {
                    "2023": null
                },
                "household_tax": {
                    "2023": null
                },
                "main_residence_value": {
                    "2023": 0
                },
                "members": [
                    "adult_1"
                ],
                "total_wealth": {
                    "2023": 0
                }
            }
        },
        "people": {
            "adult_1": {
                "age": {
                    "2023": 18
                },
                "employment_income": {
                    "2023": 0
                },
                "pension_income": {
                    "2023": 0
                },
                "state_pension": {
                    "2023": 0
                }
            }
        }
    }',
	"nd6A9c//YrYwDUr6/va/TX4/BYUtoaoanyDDxLn5ufk="
);