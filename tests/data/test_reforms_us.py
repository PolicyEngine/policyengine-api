raise_bracket_7 = {
    "data": {"gov.irs.income.bracket.rates.7": {"2024-01-01.2100-12-31": 0.8}}
}

raise_ctc_amount = {
    "data": {
        "gov.irs.credits.ctc.amount.base[0].amount": {
            "2024-01-01.2100-12-31": 5000
        }
    }
}

remove_ssi = {
    "data": {"gov.ssa.ssi.amount.individual": {"2024-01-01.2100-12-31": 0}}
}

lower_salt_cap = {
    "data": {
        "gov.irs.deductions.itemized.salt_and_real_estate.cap.HEAD_OF_HOUSEHOLD": {
            "2024-01-01.2100-12-31": 2_000
        }
    }
}

raise_standard_deduction = {
    "data": {
        "gov.irs.deductions.standard.amount.SINGLE": {
            "2024-01-01.2100-12-31": 20_000
        }
    }
}


all_policies = [
    raise_bracket_7,
    raise_ctc_amount,
    remove_ssi,
    lower_salt_cap,
    raise_standard_deduction,
]
