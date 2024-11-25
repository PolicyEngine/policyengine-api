increase_co_eitc_match = {
    "data": {
        "gov.states.co.tax.income.credits.eitc.match": {
            "2024-01-01.2100-12-31": 0.8
        },
    },
    "region": "co",
}

decrease_co_ssi_supplement_age = {
    "data": {
        "gov.states.co.ssa.state_supplement.age_range[1].threshold": {
            "2024-01-01.2100-12-31": 40
        },
    },
    "region": "co",
}

increase_co_tanf = {
    "data": {
        "gov.states.co.cdhs.tanf.grant_standard.main.2.2": {
            "2024-01-01.2100-12-31": 1000
        }
    },
    "region": "co",
}

decrease_ca_fytc_amount = {
    "data": {
        "gov.states.ca.tax.income.credits.foster_youth.amount[1].amount": {
            "2024-01-01.2100-12-31": 500
        },
    },
    "region": "ca",
}

increase_dc_income_tax_top_rate = {
    "data": {
        "gov.states.dc.tax.income.rates[6].rate": {
            "2024-01-01.2100-12-31": 0.15
        },
    },
    "region": "dc",
}

remove_hi_standard_deduction = {
    "data": {
        "gov.states.hi.tax.income.deductions.standard.amount.HEAD_OF_HOUSEHOLD": {
            "2024-01-01.2100-12-31": 0
        },
    },
    "region": "hi",
}

or_rebate_measure_118 = {
    "data": {
        "gov.contrib.ubi_center.basic_income.amount.person.flat": {
            "2024-01-01.2100-12-31": 1160
        },
    },
    "region": "or",
}


all_policies = [
    increase_co_eitc_match,
    decrease_co_ssi_supplement_age,
    increase_co_tanf,
    decrease_ca_fytc_amount,
    increase_dc_income_tax_top_rate,
    remove_hi_standard_deduction,
    or_rebate_measure_118,
]
