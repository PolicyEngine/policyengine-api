valid_input_data = {
  "time_period": "2022",
  "region": "us",
  "currency": "usd",
  "policy": {},
  "impact": {
    "poverty_by_race": {
      "poverty": {}
    },
    "budget": {},
    "intra_decile": {},
    "decile": {},
    "inequality": {},
    "poverty": {
      "poverty": {},
      "deep_poverty": {},
    },
    "poverty_by_gender": {}
  },
  "relevant_parameters": {},
  "relevant_parameter_baseline_values": {},
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