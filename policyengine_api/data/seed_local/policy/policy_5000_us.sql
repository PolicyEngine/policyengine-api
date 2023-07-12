INSERT INTO policy (id, country_id, label, api_version, policy_json, policy_hash)
VALUES (
	5000,
	"us",
	NULL,
	"0.9.5",
	{
        "gov.abolitions.above_the_line_deductions": {
            "2023-01-01.2028-12-31": true
        },
        "gov.abolitions.additional_medicare_tax": {
            "2023-01-01.2028-12-31": true
        },
        "gov.abolitions.additional_standard_deduction": {
            "2023-01-01.2028-12-31": true
        },
        "gov.abolitions.basic_standard_deduction": {
            "2023-01-01.2028-12-31": true
        },
        "gov.abolitions.household_refundable_tax_credits": {
            "2023-01-01.2028-12-31": true
        },
        "gov.abolitions.taxable_income_deductions_if_itemizing": {
            "2023-01-01.2028-12-31": true
        },
        "gov.abolitions.taxable_income_deductions_if_not_itemizing": {
            "2023-01-01.2028-12-31": true
        }
    },
	"0ZTQK2YrUBpUN+FYoAXYYmYSrn+j417oMsGx6IPynlA="
);