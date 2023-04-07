from microdf import MicroDataFrame, MicroSeries
import numpy as np


def budgetary_impact(baseline: dict, reform: dict) -> dict:
    budgetary_impact = (
        baseline["total_net_income"] - reform["total_net_income"]
    )
    tax_revenue_impact = reform["total_tax"] - baseline["total_tax"]
    benefit_spending_impact = (
        reform["total_benefits"] - baseline["total_benefits"]
    )
    return dict(
        budgetary_impact=budgetary_impact,
        tax_revenue_impact=tax_revenue_impact,
        benefit_spending_impact=benefit_spending_impact,
        households=sum(baseline["household_weight"]),
        baseline_net_income=baseline["total_net_income"],
    )


def decile_impact(baseline: dict, reform: dict) -> dict:
    """
    Compare the impact of a reform on the deciles of the population.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on the deciles of the population.
    """
    baseline_income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    reform_income = MicroSeries(
        reform["household_net_income"], weights=baseline_income.weights
    )
    decile = MicroSeries(baseline["household_income_decile"])
    income_change = reform_income - baseline_income
    rel_income_change_by_decile = (
        income_change.groupby(decile).sum()
        / baseline_income.groupby(decile).sum()
    )
    avg_income_change_by_decile = (
        income_change.groupby(decile).sum()
        / baseline_income.groupby(decile).count()
    )
    rel_decile_dict = rel_income_change_by_decile.to_dict()
    avg_decile_dict = avg_income_change_by_decile.to_dict()
    result = dict(
        relative={int(k): v for k, v in rel_decile_dict.items()},
        average={int(k): v for k, v in avg_decile_dict.items()},
    )
    # Remove 0 entries if they exist.
    if 0 in result["relative"]:
        del result["relative"][0]
    if 0 in result["average"]:
        del result["average"][0]
    return result


def wealth_decile_impact(baseline: dict, reform: dict) -> dict:
    """
    Compare the impact of a reform on the deciles of the population.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on the deciles of the population.
    """
    baseline_income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    reform_income = MicroSeries(
        reform["household_net_income"], weights=baseline_income.weights
    )
    decile = MicroSeries(baseline["household_wealth_decile"])
    income_change = reform_income - baseline_income
    rel_income_change_by_decile = (
        income_change.groupby(decile).sum()
        / baseline_income.groupby(decile).sum()
    )
    avg_income_change_by_decile = (
        income_change.groupby(decile).sum()
        / baseline_income.groupby(decile).count()
    )
    rel_decile_dict = rel_income_change_by_decile.to_dict()
    avg_decile_dict = avg_income_change_by_decile.to_dict()
    result = dict(
        relative={int(k): v for k, v in rel_decile_dict.items()},
        average={int(k): v for k, v in avg_decile_dict.items()},
    )
    # Remove 0 entries if they exist.
    if 0 in result["relative"]:
        del result["relative"][0]
    if 0 in result["average"]:
        del result["average"][0]
    return result


def inequality_impact(baseline: dict, reform: dict) -> dict:
    """
    Compare the impact of a reform on inequality.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on inequality.
    """

    return dict(
        gini=dict(
            baseline=baseline["gini"],
            reform=reform["gini"],
        ),
        top_10_pct_share=dict(
            baseline=baseline["top_10_percent_share"],
            reform=reform["top_10_percent_share"],
        ),
        top_1_pct_share=dict(
            baseline=baseline["top_1_percent_share"],
            reform=reform["top_1_percent_share"],
        ),
    )


def poverty_impact(baseline: dict, reform: dict) -> dict:
    """
    Compare the impact of a reform on poverty.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on poverty.
    """
    baseline_poverty = MicroSeries(
        baseline["person_in_poverty"], weights=baseline["person_weight"]
    )
    baseline_deep_poverty = MicroSeries(
        baseline["person_in_deep_poverty"], weights=baseline["person_weight"]
    )
    reform_poverty = MicroSeries(
        reform["person_in_poverty"], weights=baseline_poverty.weights
    )
    reform_deep_poverty = MicroSeries(
        reform["person_in_deep_poverty"], weights=baseline_poverty.weights
    )
    age = MicroSeries(baseline["age"])

    poverty = dict(
        child=dict(
            baseline=float(baseline_poverty[age < 18].mean()),
            reform=float(reform_poverty[age < 18].mean()),
        ),
        adult=dict(
            baseline=float(baseline_poverty[(age >= 18) & (age < 65)].mean()),
            reform=float(reform_poverty[(age >= 18) & (age < 65)].mean()),
        ),
        senior=dict(
            baseline=float(baseline_poverty[age >= 65].mean()),
            reform=float(reform_poverty[age >= 65].mean()),
        ),
        all=dict(
            baseline=float(baseline_poverty.mean()),
            reform=float(reform_poverty.mean()),
        ),
    )

    deep_poverty = dict(
        child=dict(
            baseline=float(baseline_deep_poverty[age < 18].mean()),
            reform=float(reform_deep_poverty[age < 18].mean()),
        ),
        adult=dict(
            baseline=float(
                baseline_deep_poverty[(age >= 18) & (age < 65)].mean()
            ),
            reform=float(reform_deep_poverty[(age >= 18) & (age < 65)].mean()),
        ),
        senior=dict(
            baseline=float(baseline_deep_poverty[age >= 65].mean()),
            reform=float(reform_deep_poverty[age >= 65].mean()),
        ),
        all=dict(
            baseline=float(baseline_deep_poverty.mean()),
            reform=float(reform_deep_poverty.mean()),
        ),
    )

    return dict(
        poverty=poverty,
        deep_poverty=deep_poverty,
    )


def intra_decile_impact(baseline: dict, reform: dict) -> dict:
    baseline_income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    reform_income = MicroSeries(
        reform["household_net_income"], weights=baseline_income.weights
    )
    people = MicroSeries(
        baseline["household_count_people"], weights=baseline_income.weights
    )
    decile = MicroSeries(baseline["household_income_decile"]).values
    absolute_change = (reform_income - baseline_income).values
    capped_baseline_income = np.maximum(baseline_income.values, 1)
    capped_reform_income = (
        np.maximum(reform_income.values, 1) + absolute_change
    )
    income_change = (
        capped_reform_income - capped_baseline_income
    ) / capped_baseline_income

    # Within each decile, calculate the percentage of people who:
    # 1. Gained more than 5% of their income
    # 2. Gained between 0% and 5% of their income
    # 3. Had no change in income
    # 3. Lost between 0% and 5% of their income
    # 4. Lost more than 5% of their income

    outcome_groups = {}
    all_outcomes = {}
    BOUNDS = [-np.inf, -0.05, -1e-3, 1e-3, 0.05, np.inf]
    LABELS = [
        "Lose more than 5%",
        "Lose less than 5%",
        "No change",
        "Gain less than 5%",
        "Gain more than 5%",
    ]
    for lower, upper, label in zip(BOUNDS[:-1], BOUNDS[1:], LABELS):
        outcome_groups[label] = []
        for i in range(1, 11):
            in_decile = decile == i
            in_group = (income_change > lower) & (income_change <= upper)
            in_both = in_decile & in_group
            outcome_groups[label].append(
                float(people[in_both].sum() / people[in_decile].sum())
            )
        all_outcomes[label] = sum(outcome_groups[label]) / 10
    return dict(deciles=outcome_groups, all=all_outcomes)


def intra_wealth_decile_impact(baseline: dict, reform: dict) -> dict:
    baseline_income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    reform_income = MicroSeries(
        reform["household_net_income"], weights=baseline_income.weights
    )
    people = MicroSeries(
        baseline["household_count_people"], weights=baseline_income.weights
    )
    decile = MicroSeries(baseline["household_wealth_decile"]).values
    absolute_change = (reform_income - baseline_income).values
    capped_baseline_income = np.maximum(baseline_income.values, 1)
    capped_reform_income = (
        np.maximum(reform_income.values, 1) + absolute_change
    )
    income_change = (
        capped_reform_income - capped_baseline_income
    ) / capped_baseline_income

    # Within each decile, calculate the percentage of people who:
    # 1. Gained more than 5% of their income
    # 2. Gained between 0% and 5% of their income
    # 3. Had no change in income
    # 3. Lost between 0% and 5% of their income
    # 4. Lost more than 5% of their income

    outcome_groups = {}
    all_outcomes = {}
    BOUNDS = [-np.inf, -0.05, -1e-3, 1e-3, 0.05, np.inf]
    LABELS = [
        "Lose more than 5%",
        "Lose less than 5%",
        "No change",
        "Gain less than 5%",
        "Gain more than 5%",
    ]
    for lower, upper, label in zip(BOUNDS[:-1], BOUNDS[1:], LABELS):
        outcome_groups[label] = []
        for i in range(1, 11):
            in_decile = decile == i
            in_group = (income_change > lower) & (income_change <= upper)
            in_both = in_decile & in_group
            outcome_groups[label].append(
                float(people[in_both].sum() / people[in_decile].sum())
            )
        all_outcomes[label] = sum(outcome_groups[label]) / 10
    return dict(deciles=outcome_groups, all=all_outcomes)


def poverty_gender_breakdown(baseline: dict, reform: dict) -> dict:
    """
    Compare the impact of a reform on poverty.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on poverty.
    """
    if baseline["is_male"] is None:
        return {}
    baseline_poverty = MicroSeries(
        baseline["person_in_poverty"], weights=baseline["person_weight"]
    )
    baseline_deep_poverty = MicroSeries(
        baseline["person_in_deep_poverty"], weights=baseline["person_weight"]
    )
    reform_poverty = MicroSeries(
        reform["person_in_poverty"], weights=baseline_poverty.weights
    )
    reform_deep_poverty = MicroSeries(
        reform["person_in_deep_poverty"], weights=baseline_poverty.weights
    )
    is_male = MicroSeries(baseline["is_male"])

    poverty = dict(
        male=dict(
            baseline=float(baseline_poverty[is_male].mean()),
            reform=float(reform_poverty[is_male].mean()),
        ),
        female=dict(
            baseline=float(baseline_poverty[~is_male].mean()),
            reform=float(reform_poverty[~is_male].mean()),
        ),
    )

    deep_poverty = dict(
        male=dict(
            baseline=float(baseline_deep_poverty[is_male].mean()),
            reform=float(reform_deep_poverty[is_male].mean()),
        ),
        female=dict(
            baseline=float(baseline_deep_poverty[~is_male].mean()),
            reform=float(reform_deep_poverty[~is_male].mean()),
        ),
    )

    return dict(
        poverty=poverty,
        deep_poverty=deep_poverty,
    )


def compare_economic_outputs(baseline: dict, reform: dict) -> dict:
    """
    Compare the economic outputs of two economies.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The comparison of the two economies.
    """
    if baseline.get("type") == "general":
        budgetary_impact_data = budgetary_impact(baseline, reform)
        decile_impact_data = decile_impact(baseline, reform)
        inequality_impact_data = inequality_impact(baseline, reform)
        poverty_impact_data = poverty_impact(baseline, reform)
        poverty_by_gender_data = poverty_gender_breakdown(baseline, reform)
        intra_decile_impact_data = intra_decile_impact(baseline, reform)
        try:
            wealth_decile_impact_data = wealth_decile_impact(baseline, reform)
            intra_wealth_decile_impact_data = intra_wealth_decile_impact(
                baseline, reform
            )
        except:
            wealth_decile_impact_data = {}
            intra_wealth_decile_impact_data = {}

        return dict(
            budget=budgetary_impact_data,
            decile=decile_impact_data,
            inequality=inequality_impact_data,
            poverty=poverty_impact_data,
            poverty_by_gender=poverty_by_gender_data,
            intra_decile=intra_decile_impact_data,
            wealth_decile=wealth_decile_impact_data,
            intra_wealth_decile=intra_wealth_decile_impact_data,
        )
    elif baseline.get("type") == "cliff":
        return dict(
            baseline=dict(
                cliff_gap=baseline["cliff_gap"],
                cliff_share=baseline["cliff_share"],
            ),
            reform=dict(
                cliff_gap=reform["cliff_gap"],
                cliff_share=reform["cliff_share"],
            ),
        )
