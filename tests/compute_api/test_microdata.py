def test_uk_microsim():
    from policyengine_uk import Microsimulation

    simulation = Microsimulation()
    simulation.calculate("household_net_income")


def test_us_microsim():
    print(f"About to import")
    from policyengine_us import Microsimulation
    print("Imported. Now instantiating microsim")
    simulation = Microsimulation()
    print(f"Now running the tax-benefit system")
    simulation.calculate("household_net_income")
    print(f"Done")
