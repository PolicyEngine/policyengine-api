INSERT OR REPLACE INTO policy (id, country_id, label, api_version, policy_json, policy_hash)
VALUES (
	-2,
	"uk",
	"Sample dataset - duplicate of UK policy #9,750 in live database",
	"0.45.0",
	'{
    	"gov.hmrc.income_tax.rates.uk[0].rate": {
    	    "2023-01-01.2028-12-31": 0.039900000000000005
    	}
    }',
	"XOaSxH+5XIVgbOcpRnBdegcKUSkOZiCGfUSxRAkZuWo="
);