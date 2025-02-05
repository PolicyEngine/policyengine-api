simulation_analysis_template = """
  I'm using PolicyEngine, a free, open source tool to compute the impact of 
  public policy. I'm writing up an economic analysis of a hypothetical tax-benefit 
  policy reform. Please write the analysis for me using the details below, in 
  their order. You should:

  - First explain each provision of the reform, noting that it's hypothetical and 
  won't represents policy reforms for {time_period} and {region}. Explain how 
  the parameters are changing from the baseline to the reform values using the given data.

  {enhanced_cps_template}

  - Round large numbers like: {currency}3.1 billion, {currency}300 million, 
  {currency}106,000, {currency}1.50 (never {currency}1.5).

  - Round percentages to one decimal place.

  - Avoid normative language like 'requires', 'should', 'must', and use quantitative statements 
  over general adjectives and adverbs. If you don't know what something is, don't make it up.

  - Avoid speculating about the intent of the policy or inferring any motives; only describe the 
  observable effects and impacts of the policy. Refrain from using subjective language or making 
  assumptions about the recipients and their needs.

  - Use the active voice where possible; for example, write phrases where the reform is the subject,
  such as "the reform [or a description of the reform] reduces poverty by x%".

  - Use {dialect} English spelling and grammar.

  - Cite PolicyEngine {country_id_uppercase} v{selected_version} and the {data_source} microdata 
  when describing policy impacts.

  - When describing poverty impacts, note that the poverty measure reported is {poverty_measure}

  - Don't use headers, but do use Markdown formatting. Use - for bullets, and include a newline after each bullet.

  - Include the following embeds inline, without a header so it flows.

  - Immediately after you describe the changes by decile, include the text: '{{{{distributionalImpact.incomeDecile.relative}}}}'

  - And after the poverty rate changes, include the text: '{{{{povertyImpact.regular.byAge}}}}'

  {poverty_rate_change_text}

  - And after the inequality changes, include the text: "{{{{inequalityImpact}}}}"

  - Make sure to accurately represent the changes observed in the data.

  - This JSON snippet describes the default parameter values: {relevant_parameter_baseline_values}
  
  - This JSON snippet describes the baseline and reform policies being compared: {policy}

  - {policy_label} has the following impacts from the PolicyEngine microsimulation model: 

  - This JSON snippet describes the relevant parameters with more details: {relevant_parameters}

  - This JSON describes the total budgetary impact, the change to tax revenues and benefit 
  spending (ignore 'households' and 'baseline_net_income': {impact_budget}

  - This JSON describes how common different outcomes were at each income decile: {impact_intra_decile}

  - This JSON describes the average and relative changes to income by each income decile: {impact_decile}

  - This JSON describes the baseline and reform poverty rates by age group 
  (describe the relative changes): {impact_poverty}

  - This JSON describes the baseline and reform deep poverty rates by age group 
  (describe the relative changes): {impact_deep_poverty}

  - This JSON describes the baseline and reform poverty and deep poverty rates 
  by gender (briefly describe the relative changes): {impact_poverty_by_gender}

  {poverty_by_race_text}

  - This JSON describes three inequality metrics in the baseline and reform, the Gini 
  coefficient of income inequality, the share of income held by the top 10% of households 
  and the share held by the top 1% (describe the relative changes): {impact_inequality}

  {audience_description}
"""

audience_descriptions = {
    "ELI5": "Write this for a layperson who doesn't know much about economics or policy. Explain fundamental concepts like taxes, poverty rates, and inequality as needed.",
    "Normal": "Write this for a policy analyst who knows a bit about economics and policy.",
    "Wonk": "Write this for a policy analyst who knows a lot about economics and policy. Use acronyms and jargon if it makes the content more concise and informative.",
}
