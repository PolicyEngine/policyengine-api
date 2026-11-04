"""Policy paths in the installed US and UK models, for parameter-path checks."""

import pytest

POLICY_PERIOD = "2026-01-01.2026-12-31"

# Paths that do not name a parameter a policy can set a value on, by country.
NON_PARAMETER_PATHS = {
    "us": {
        "unknown path": "gov.x",
        "parameter group": "gov.irs.credits.ctc.amount",
        "parameter scale": "gov.irs.credits.ctc.amount.base",
        "scale bracket": "gov.irs.credits.ctc.amount.base[0]",
        "missing contributed parameter": "gov.contrib.states.mt.hb1.in_effect",
    },
    "uk": {
        "unknown path": "gov.x",
        "parameter group": "gov.hmrc.income_tax.rates",
        "parameter scale": "gov.hmrc.income_tax.rates.uk",
        "scale bracket": "gov.hmrc.income_tax.rates.uk[0]",
        "missing contributed parameter": (
            "gov.contrib.ubi_center.basic_income.in_effect"
        ),
    },
}

# Parameters a policy can set: a scale bracket's value, a contributed parameter
# and a contributed scale bracket's value.
SETTABLE_PARAMETER_PATHS = {
    "us": (
        "gov.irs.credits.ctc.amount.base[0].amount",
        "gov.contrib.states.mt.ctc.in_effect",
        "gov.contrib.states.mt.ctc.amount[0].amount",
    ),
    "uk": (
        "gov.hmrc.income_tax.rates.uk[0].rate",
        "gov.contrib.ubi_center.basic_income.amount.flat",
        "gov.contrib.ubi_center.wealth_tax[0].rate",
    ),
}

NON_PARAMETER_CASES = [
    pytest.param(country_id, path, id=f"{country_id}-{description}")
    for country_id, paths_by_description in NON_PARAMETER_PATHS.items()
    for description, path in paths_by_description.items()
]


def policy_data(*parameter_paths: str) -> dict[str, dict[str, int]]:
    """Return a policy that sets each path to 1 for the test period."""
    return {parameter_path: {POLICY_PERIOD: 1} for parameter_path in parameter_paths}
