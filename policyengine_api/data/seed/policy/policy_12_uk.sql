INSERT INTO policy (id, country_id, label, api_version, policy_json, policy_hash)
VALUES (
	12,
	"uk",
	"Sample dataset - duplicate of UK policy #15,000 in live database",
	"0.50.1",
	{
        "gov.hmrc.income_tax.rates.dividends[0].rate": {
            "2023-01-01.2028-12-31": 0.33
    	}
	},
	"0TpYP9bLFAG2whtgv8DxMRpNTzyfjoCFMVkXMjtyz5w="
);