def test_uk_microsim():
    from policyengine_uk import Microsimulation

    simulation = Microsimulation()
    simulation.calculate("household_net_income")


def test_us_microsim():
    from policyengine_us import Microsimulation
    simulation = Microsimulation()
    simulation.memory_config = MemoryConfig(0.4)
    simulation.calculate("household_net_income")
