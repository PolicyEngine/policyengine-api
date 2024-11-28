raise_ctc_amount = {
    "name": "Raise CTC base amount",
    "data": {
        "gov.irs.credits.ctc.amount.base[0].amount": {
            "2024-01-01.2100-12-31": 5000
        }
    },
}

lower_salt_cap = {
    "name": "Lower SALT cap for head of household filers",
    "data": {
        "gov.irs.deductions.itemized.salt_and_real_estate.cap.HEAD_OF_HOUSEHOLD": {
            "2024-01-01.2100-12-31": 2_000
        }
    },
}

raise_standard_deduction = {
    "name": "Raise standard deduction for single filers",
    "data": {
        "gov.irs.deductions.standard.amount.SINGLE": {
            "2024-01-01.2100-12-31": 20_000
        }
    },
}


all_policies = [
    raise_ctc_amount,
    lower_salt_cap,
    raise_standard_deduction,
]
