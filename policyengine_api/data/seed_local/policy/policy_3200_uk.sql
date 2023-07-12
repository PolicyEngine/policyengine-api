INSERT INTO policy (id, country_id, label, api_version, policy_json, policy_hash)
VALUES (
	3200,
	"uk",
	NULL,
	"0.7.11",
	{
        "gov.contrib.ubi_center.basic_income.amount.by_age.senior": {
            "2023-01-01.2028-12-31": "44.35"
        },
        "gov.contrib.ubi_center.basic_income.amount.by_age.working_age": {
            "2023-01-01.2028-12-31": "70.95"
        },
        "gov.contrib.ubi_center.basic_income.interactions.include_in_means_tests": {
            "2023-01-01.2028-12-31": true
        },
        "gov.hmrc.income_tax.allowances.dividend_allowance": {
            "2023-01-01.2028-12-31": "0"
        },
        "gov.hmrc.income_tax.allowances.personal_allowance.amount": {
            "2023-01-01.2028-12-31": "1040"
        },
        "gov.hmrc.income_tax.allowances.personal_allowance.reduction_rate": {
            "2023-01-01.2028-12-31": 0
        },
        "gov.hmrc.income_tax.rates.dividends[0].rate": {
            "2023-01-01.2028-12-31": 0.2
        },
        "gov.hmrc.income_tax.rates.dividends[1].rate": {
            "2023-01-01.2028-12-31": 0.4
        },
        "gov.hmrc.income_tax.rates.dividends[1].threshold": {
            "2023-01-01.2028-12-31": "49230"
        },
        "gov.hmrc.income_tax.rates.dividends[2].rate": {
            "2023-01-01.2028-12-31": 0.45
        },
        "gov.hmrc.income_tax.rates.scotland.post_starter_rate[3].threshold": {
            "2023-01-01.2028-12-31": "42460"
        },
        "gov.hmrc.income_tax.rates.uk[1].threshold": {
            "2023-01-01.2028-12-31": "49230"
        },
        "gov.hmrc.national_insurance.class_1.thresholds.primary_threshold": {
            "2023-01-01.2028-12-31": "0"
        },
        "gov.hmrc.national_insurance.class_1.thresholds.upper_earnings_limit": {
            "2023-01-01.2028-12-31": "946.73"
        },
        "gov.hmrc.national_insurance.class_2.small_profits_threshold": {
            "2023-01-01.2028-12-31": "1040"
        },
        "gov.hmrc.national_insurance.class_4.thresholds.lower_profits_limit": {
            "2023-01-01.2028-12-31": "1040"
        },
        "gov.hmrc.national_insurance.class_4.thresholds.upper_profits_limit": {
            "2023-01-01.2028-12-31": "49230"
        }
    },
	"G6N0rt8O6J1mHN4DAAHHnFB8qYRV56opyYx44kF+UHE="
);