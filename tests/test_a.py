

def test_a():
    print(f"About to import", flush=True)
    from policyengine_us import Microsimulation
    print("Imported. Now instantiating microsim", flush=True)
    simulation = Microsimulation()
    print(f"Now running the tax-benefit system", flush=True)
    simulation.calculate("household_net_income")
    print(f"Done", flush=True)
