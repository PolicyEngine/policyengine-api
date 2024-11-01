import time
from tqdm import tqdm
import numpy as np


def calc_chunks(sim, variables, count_chunks=5):
    for i in range(len(variables)):
        if isinstance(variables[i], str):
            variables[i] = (variables[i], sim.default_calculation_period)
    variables = [
        (variable, time_period)
        for variable, time_period in variables
        if variable in sim.tax_benefit_system.variables
    ]
    if count_chunks > 1:
        households = sim.calculate("household_id", 2024).values
        chunk_size = len(households) // count_chunks + 1
        input_df = sim.to_input_dataframe()

        variable_data = {
            variable: np.array([]) for variable, time_period in variables
        }

        for i in tqdm(range(count_chunks)):
            households_in_chunk = households[
                i * chunk_size : (i + 1) * chunk_size
            ]
            chunk_df = input_df[
                input_df["household_id__2024"].isin(households_in_chunk)
            ]

            subset_sim = type(sim)(dataset=chunk_df, reform=sim.reform)
            subset_sim.default_calculation_period = (
                sim.default_calculation_period
            )

            for variable, time_period in variables:
                chunk_values = subset_sim.calculate(
                    variable, time_period
                ).values
                variable_data[variable] = np.concatenate(
                    [variable_data[variable], chunk_values]
                )

        for variable, time_period in variables:
            sim.set_input(variable, time_period, variable_data[variable])

    return sim
