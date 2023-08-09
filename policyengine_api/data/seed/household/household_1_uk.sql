INSERT INTO household (id, country_id, label, api_version, household_json, household_hash)
VALUES (
	1,
	"uk",
	"Sample dataset - duplicate of UK household #4125 in live database",
	"0.8.9",
	{
        "households": {
            "household": {
                "household_benefits": {
                    "2023": null
                },
                "household_net_income": {
                    "2023": null
                },
                "household_tax": {
                    "2023": null
                },
                "members": [
                    "parent",
                    "child"
                ]
            }
        },
        "people": {
            "child": {
                "age": {
                    "2023": 10
                }
            },
            "parent": {
                "age": {
                    "2023": 35
                },
                "employment_income": {
                    "2023": 30000
                }
            }
        }
    },
	"UdeoPHrOn8g6qnMvyfBUjjGVl1ClHBpNGnvIC+N5oIQ="
);