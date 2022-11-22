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
    return dict(
        relative={int(k): v for k, v in rel_decile_dict.items()},
        average={int(k): v for k, v in avg_decile_dict.items()},
    )


def inequality_impact(baseline: dict, reform: dict) -> dict:
    """
    Compare the impact of a reform on inequality.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on inequality.
    """
    baseline_income = MicroSeries(
        baseline["equiv_household_net_income"],
        weights=np.array(baseline["household_weight"])
        * np.array(baseline["household_count_people"]),
    )
    reform_income = MicroSeries(
        reform["equiv_household_net_income"], weights=baseline_income.weights
    )

    baseline_gini = baseline_income.gini()
    reform_gini = reform_income.gini()

    return dict(
        gini=dict(
            baseline=float(baseline_gini),
            reform=float(reform_gini),
        )
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
    reform_poverty = MicroSeries(
        reform["person_in_poverty"], weights=baseline_poverty.weights
    )
    age = MicroSeries(baseline["age"])

    return dict(
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
    inequality_impact_data = inequality_impact(baseline, reform)
    poverty_impact_data = poverty_impact(baseline, reform)

    return dict(
        budget=budgetary_impact_data,
        decile=decile_impact_data,
        inequality=inequality_impact_data,
        poverty=poverty_impact_data,
    )
