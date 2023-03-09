def test_uk_microsim():
    from policyengine_uk import Microsimulation

    simulation = Microsimulation()
    simulation.calculate("household_net_income")

def test_us_system():
    from policyengine_us import Microsimulation

def test_us_microsim_instantiates():
    from policyengine_us import Microsimulation

    simulation = Microsimulation()

def test_us_microsim_calculates():
    from policyengine_us import Microsimulation

    simulation = Microsimulation()
    simulation.calculate("income_tax")

def test_us_microsim():
    from policyengine_us import Microsimulation
    from policyengine_core.experimental import MemoryConfig
    simulation = Microsimulation()
    simulation.memory_config = MemoryConfig(0.4)
    simulation.calculate("household_net_income")
