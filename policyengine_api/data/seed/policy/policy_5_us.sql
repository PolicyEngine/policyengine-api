INSERT INTO policy (id, country_id, label, api_version, policy_json, policy_hash)
VALUES (
	5,
	"us",
	"Sample dataset - duplicate of US policy #22,000 in live database",
	"0.403.2",
	{
        "gov.abolitions.nm_income_tax_before_refundable_credits": {
            "2023-01-01.2028-12-31": true
        },
        "gov.abolitions.nm_refundable_credits": {
            "2023-01-01.2028-12-31": true
        }
    },
	"xoyoNJSle/sorA78DLGWVejE+kdUlXro+/xKAtAx1sc="
);