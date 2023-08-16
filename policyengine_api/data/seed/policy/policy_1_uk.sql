INSERT OR REPLACE INTO policy (id, country_id, label, api_version, policy_json, policy_hash)
VALUES (
	-1,
	"uk",
	"Sample dataset - duplicate of UK policy #3,300 in live database",
	"0.7.11",
	'{
        "gov.dwp.LHA.rate_caps.beds_2": {
            "2023-01-01.2028-12-31": "180"
        }
    }',
	"rWg/wZY90XkAAehYyEjJi/Vk+lEoz8edpKLUclnxjaA="
);