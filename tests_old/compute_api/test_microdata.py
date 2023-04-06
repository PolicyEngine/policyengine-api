def test_uk_microdata():
    from policyengine_uk import Microsimulation

    sim = Microsimulation()
    sim.calculate("household_net_income")
