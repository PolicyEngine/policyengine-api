valid_tracer_output = [
    "        snap<2027, (default)> = [6769.799]",
    "          snap<2027-01, (default)> = [561.117]",
    "            takes_up_snap_if_eligible<2027-01, (default)> = [ True]",
    "            snap_normal_allotment<2027-01, (default)> = [561.117]",
    "              is_snap_eligible<2027-01, (default)> = [ True]",
    "                meets_snap_net_income_test<2027-01, (default)> = [ True]",
    "                  snap_net_income_fpg_ratio<2027-01, (default)> = [0.]",
    "                    snap_net_income<2027-01, (default)> = [0.]",
    "                    snap_fpg<2027-01, (default)> = [1806.4779]",
]

invalid_tracer_output = {
    "variable": "only_government_benefit <1500>",
    "variable": "    market_income <1000>",
}

spliced_valid_tracer_output_root_variable = valid_tracer_output[0:]

spliced_valid_tracer_output_nested_variable = valid_tracer_output[2:3]

spliced_valid_tracer_output_leaf_variable = valid_tracer_output[8:]

empty_tracer = []
