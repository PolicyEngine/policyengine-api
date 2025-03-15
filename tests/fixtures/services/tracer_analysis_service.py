valid_tracer_output = [
    "only_government_benefit <1500>",
    "    market_income <1000>",
    "        employment_income <1000>",
    "            main_employment_income <1000 >",
    "    non_market_income <500>",
    "        pension_income <500>",
]

invalid_tracer_output = {
    "variable": "only_government_benefit <1500>",
    "variable": "    market_income <1000>",
}

valid_tracer_output_with_suffixed_target_variable = [
    "only_government_benefit <1500>",
    "    market_income <1000>",
    "        employment_income <1000>",
    "            main_employment_income_dummy <1000 >",
    "    non_market_income <500>",
    "        main_employment_income <1000 >",
]

spliced_tracer_output_with_suffixed_target_variable = (
    valid_tracer_output_with_suffixed_target_variable[5:]
)

spliced_valid_tracer_output_employment_income = valid_tracer_output[2:4]

spliced_valid_tracer_output_pension_income = valid_tracer_output[5:]

empty_tracer = []
