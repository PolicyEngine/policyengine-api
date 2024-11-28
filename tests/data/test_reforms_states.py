increase_co_eitc_match = {
    "name": "Increase Colorado EITC match",
    "data": {
        "gov.states.co.tax.income.credits.eitc.match": {
            "2024-01-01.2100-12-31": 0.8
        },
    },
    "region": "co",
}

decrease_ca_fytc_amount = {
    "name": "Decrease California FYTC amount",
    "data": {
        "gov.states.ca.tax.income.credits.foster_youth.amount[1].amount": {
            "2024-01-01.2100-12-31": 500
        },
    },
    "region": "ca",
}

remove_hi_standard_deduction = {
    "name": "Remove Hawaii standard deduction for heads of household",
    "data": {
        "gov.states.hi.tax.income.deductions.standard.amount.HEAD_OF_HOUSEHOLD": {
            "2024-01-01.2100-12-31": 0
        },
    },
    "region": "hi",
}

or_rebate_measure_118 = {
    "name": "Oregon Rebate Measure 118",
    "data": {
        "gov.contrib.ubi_center.basic_income.amount.person.flat": {
            "2024-01-01.2100-12-31": 1160
        },
    },
    "region": "or",
}


all_policies = [
    increase_co_eitc_match,
    decrease_ca_fytc_amount,
    remove_hi_standard_deduction,
    or_rebate_measure_118,
]
