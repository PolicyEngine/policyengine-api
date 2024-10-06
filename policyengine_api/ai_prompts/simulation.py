import json

audience_descriptions = {
    "ELI5": "Write this for a five-year-old who doesn't know anything about economics or policy. Explain fundamental concepts like taxes, poverty rates, and inequality as needed.",
    "Normal":
      "Write this for a policy analyst who knows a bit about economics and policy.",
    "Wonk": "Write this for a policy analyst who knows a lot about economics and policy. Use acronyms and jargon if it makes the content more concise and informative.",
}

def generate_simulation_analysis_prompt(
    time_period,
    region,
    currency,
    policy,
    impact,
    relevant_parameters,
    relevant_parameter_baseline_values,
    is_enhanced_cps,
    selected_version,
    country_id,
    policy_label
):
    return f"""
        I'm using PolicyEngine, a free, open source tool to compute the impact of 
        public policy. I'm writing up an economic analysis of a hypothetical tax-benefit 
        policy reform. Please write the analysis for me using the details below, in 
        their order. You should:
    
        * First explain each provision of the reform, noting that it's hypothetical and 
        won't represents policy reforms for {time_period} and {region}. Explain how 
        the parameters are changing from the baseline to the reform values using the given data.

        {'''Explicitly mention that this analysis uses PolicyEngine Enhanced CPS, constructed 
        from the 2022 Current Population Survey and the 2015 IRS Public Use File, and calibrated 
        to tax, benefit, income, and demographic aggregates.''' if is_enhanced_cps else ''}
    
        * Round large numbers like: {currency}3.1 billion, {currency}300 million, 
        {currency}106,000, {currency}1.50 (never {currency}1.5).

        * Round percentages to one decimal place.

        * Avoid normative language like 'requires', 'should', 'must', and use quantitative statements 
        over general adjectives and adverbs. If you don't know what something is, don't make it up.

        * Avoid speculating about the intent of the policy or inferring any motives; only describe the 
        observable effects and impacts of the policy. Refrain from using subjective language or making 
        assumptions about the recipients and their needs.

        * Use the active voice where possible; for example, write phrases where the reform is the subject,
          such as "the reform [or a description of the reform] reduces poverty by x%".

        * Use {'British' if country_id == 'uk' else 'American'} English spelling and grammar.
    
        * Cite PolicyEngine {country_id.upper()} v{selected_version} and the {
          'PolicyEngine-enhanced 2019 Family Resources Survey' if country_id == 'uk' else '2022 Current Population Survey March Supplement'
        } microdata when describing policy impacts.

        * When describing poverty impacts, note that the poverty measure reported is {
          'absolute poverty before housing costs' if country_id == 'uk' else 'the Supplemental Poverty Measure'
        }

        * Don't use headers, but do use Markdown formatting. Use - for bullets, and include a newline after each bullet.

        * Include the following embeds inline, without a header so it flows.

        * Immediately after you describe the changes by decile, include the text: '{{decile_relative_impact}}'

        * And after the poverty rate changes, include the text: '{{poverty_impact}}'

        {f"* After the racial breakdown of poverty rate changes, include the text: '{{racial_poverty_impact}}'" if country_id == 'us' else ''}

        * And after the inequality changes, include the text: '{{inequality_impact}}'

        * Make sure to accurately represent the changes observed in the data.
  
        This JSON snippet describes the default parameter values: {json.dumps(
          relevant_parameter_baseline_values,
        )}\n

        This JSON snippet describes the baseline and reform policies being compared: {json.dumps(
          policy,
        )}\n`;

        {policy_label} has the following impacts from the PolicyEngine microsimulation model: 
  
        This JSON snippet describes the relevant parameters with more details: {json.dumps(
          relevant_parameters,
        )}
  
        This JSON describes the total budgetary impact, the change to tax revenues and benefit 
        spending (ignore 'households' and 'baseline_net_income': {json.dumps(
          impact["budget"],
        )}
  
        This JSON describes how common different outcomes were at each income decile: {json.dumps(
          impact["intra_decile"],
        )}
  
        This JSON describes the average and relative changes to income by each income decile: {json.dumps(
          impact["decile"],
        )}
  
        This JSON describes the baseline and reform poverty rates by age group (describe the relative changes): {json.dumps(
          impact["poverty"]["poverty"],
        )}
  
        This JSON describes the baseline and reform deep poverty rates by age group 
        (describe the relative changes): {json.dumps(
          impact["poverty"]["deep_poverty"],
        )}
  
        This JSON describes the baseline and reform poverty and deep poverty rates 
        by gender (briefly describe the relative changes): {json.dumps(
          impact["poverty_by_gender"],
        )}
  
        {
          '''This JSON describes the baseline and reform poverty impacts by racial group (briefly 
          describe the relative changes): {json.dumps(impact["poverty_by_race"]["poverty"])}'''
          if country_id == "us" else ""
        }
  
        This JSON describes three inequality metrics in the baseline and reform, the Gini 
        coefficient of income inequality, the share of income held by the top 10% of households 
        and the share held by the top 1% (describe the relative changes): {json.dumps(
          impact["inequality"],
        )}
    """