INSERT OR REPLACE INTO policy (id, country_id, label, api_version, policy_json, policy_hash)
VALUES (
	-5,
	"us",
	"Sample dataset - duplicate of US policy #13,000 in live database",
	"0.316.1",
	'{
        "gov.local.ny.nyc.tax.income.credits.eitc.percent[3].amount": {
            "2023-01-01.2028-12-31": ".3"
        },
        "gov.local.ny.nyc.tax.income.credits.eitc.percent[4].amount": {
            "2023-01-01.2028-12-31": ".3"
        }
    }',
	"92ZKK0KK+BmXnUKY4vsgi0fRCeKlYNqc3pb9CEOBL8o="
);