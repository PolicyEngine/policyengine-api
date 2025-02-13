valid_input_data = {
    "time_period": "2022",
    "region": "us",
    "currency": "usd",
    "policy": {"gov.test.parameter": 0.1},
    "impact": {
        "poverty_by_race": {"poverty": {}},
        "budget": {
            "baseline": 0.0,
            "reform": 0.1,
        },
        "intra_decile": {
            "baseline": {
                "1": 0.1,
                "2": 0.2,
                "3": 0.3,
                "4": 0.4,
                "5": 0.5,
                "6": 0.6,
                "7": 0.7,
                "8": 0.8,
                "9": 0.9,
                "10": 1.0,
            },
            "reform": {
                "1": 0.1,
                "2": 0.2,
                "3": 0.3,
                "4": 0.4,
                "5": 0.5,
                "6": 0.6,
                "7": 0.7,
                "8": 0.8,
                "9": 0.9,
                "10": 1.0,
            },
        },
        "decile": {
            "baseline": {
                "1": 0.1,
                "2": 0.2,
                "3": 0.3,
                "4": 0.4,
                "5": 0.5,
                "6": 0.6,
                "7": 0.7,
                "8": 0.8,
                "9": 0.9,
                "10": 1.0,
            },
            "reform": {
                "1": 0.1,
                "2": 0.2,
                "3": 0.3,
                "4": 0.4,
                "5": 0.5,
                "6": 0.6,
                "7": 0.7,
                "8": 0.8,
                "9": 0.9,
                "10": 1.0,
            },
        },
        "inequality": {
            "baseline": 0.1,
            "reform": 0.2,
        },
        "poverty": {
            "poverty": {
                "baseline": 0.1,
                "reform": 0.2,
            },
            "deep_poverty": {
                "baseline": 0.1,
                "reform": 0.2,
            },
        },
        "poverty_by_gender": {
            "baseline": 0.1,
            "reform": 0.2,
        },
    },
    "relevant_parameters": [
        {
            "parameter1": 100,
            "parameter2": 200,
        }
    ],
    "relevant_parameter_baseline_values": [
        {
            "parameter1": 100,
            "parameter2": 200,
        }
    ],
    "selected_version": "selected_version",
    "country_id": "us",
    "policy_label": "policy_label",
    "audience": "Normal",
}

valid_output_data = {
    **valid_input_data,
    "audience_description": "Write this for a policy analyst who knows a bit about economics and policy.",
    "chart_slug_distribution": "{{distributionalImpact.incomeDecile.relative}}",
    "chart_slug_poverty_age": "{{povertyImpact.regular.byAge}}",
    "chart_slug_inequality": "{{inequalityImpact}}",
    "impact_budget": "{}",
    "impact_decile": "{}",
    "impact_deep_poverty": "{}",
    "impact_intra_decile": "{}",
    "impact_inequality": "{}",
    "impact_poverty": "{}",
    "impact_poverty_by_gender": "{}",
    "poverty_by_race_text": "- This JSON describes the baseline and reform poverty impacts by racial group (briefly describe the relative changes): {}",
    "poverty_measure": "the Supplemental Poverty Measure",
    "poverty_rate_change_text": "- After the racial breakdown of poverty rate changes, include the text: '{{povertyImpact.regular.byRace}}'",
    "country_id_uppercase": "US",
    "enhanced_cps_template": "",
    "dialect": "American",
    "data_source": "2022 Current Population Survey March Supplement",
}

invalid_data_missing_input_field = {
    k: valid_input_data[k] for k in valid_input_data.keys() - {"time_period"}
}
