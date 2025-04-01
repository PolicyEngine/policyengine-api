

def test_simulation_output():
    from policyengine import Simulation

    sim = Simulation(**{
    "baseline": {},
    "country": "uk",
    "data": "hf://policyengine/policyengine-uk-data/enhanced_frs_2022_23.h5@89e20b9",
    "reform": {
        "gov.hmrc.income_tax.rates.uk[0].rate": {
        "2025-01-01.2100-12-31": 0.31
        }
    },
    "scope": "macro",
    "time_period": "2025"
    })

    result = sim.calculate_economy_comparison()

    print(result.detailed_budget["pension_credit"].baseline)

    assert result.detailed_budget["pension_credit"].baseline == -6486021485.618753

test_simulation_output()