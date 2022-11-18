from microdf import MicroDataFrame, MicroSeries


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
    decile = MicroSeries(baseline["income_decile"])
    income_change = reform_income - baseline_income
    income_change_by_decile = (
        income_change.groupby(decile).sum()
        / baseline_income.groupby(decile).sum()
    )
    return income_change_by_decile.to_dict()


def compare_economic_outputs(baseline: dict, reform: dict) -> dict:
    """
    Compare the economic outputs of two economies.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The comparison of the two economies.
    """
    budgetary_impact_data = budgetary_impact(baseline, reform)
    decile_impact_data = decile_impact(baseline, reform)

    return dict(
        budgetary_impact=budgetary_impact_data,
        decile_impact=decile_impact_data,
    )
