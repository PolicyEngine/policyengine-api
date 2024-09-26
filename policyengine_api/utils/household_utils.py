from datetime import date

def add_yearly_variables(household, simulation, metadata):
    """
    Add yearly variables to a household dict before enqueueing calculation;
    this includes all standard variables (which are guaranteed to exist in 
    CountryTaxBenefitSystem) and any structural variables that might exist
    """

    variables = metadata["variables"]
    structural_variables = metadata["structuralVariables"]
    entities = metadata["entities"]
    household_year = get_household_year(household)

    sim_variables = simulation.tax_benefit_system.variables

    for variable in variables:
        if variables[variable]["definitionPeriod"] in (
            "year",
            "month",
            "eternity",
        ):
            household = _add_variable_to_household(
                variable, variables, entities, household, household_year
            )

    for variable in structural_variables:
        """
        In the metadata, structuralVariables represents all variables that 
        COULD be instantiated by the system, while the tax_benefit_system's
        variables represent all variables that ARE instantiated by the system,
        including structural. We need to check if the structuralVariable exists
        within the actual system.
        """
        if variable in sim_variables and structural_variables[variable]["definitionPeriod"] in (
            "year",
            "month",
            "eternity",
        ):
            household = _add_variable_to_household(
                variable,
                structural_variables,
                entities,
                household,
                household_year,
            )

    return household

def _add_variable_to_household(
    variable, variables, entities, household, household_year
):
    entity_plural = entities[variables[variable]["entity"]]["plural"]
    if entity_plural in household:
        possible_entities = household[entity_plural].keys()
        for entity in possible_entities:
            if (
                not variables[variable]["name"]
                in household[entity_plural][entity]
            ):
                if variables[variable]["isInputVariable"]:
                    household[entity_plural][entity][
                        variables[variable]["name"]
                    ] = {
                        household_year: variables[variable][
                            "defaultValue"
                        ]
                    }
                else:
                    household[entity_plural][entity][
                        variables[variable]["name"]
                    ] = {household_year: None}
    
    return household


def get_household_year(household):
    """Given a household dict, get the household's year

    Args:
        household (dict): The household itself
    """

    # Set household_year based on current year
    household_year = date.today().year

    # Determine if "age" variable present within household and return list of values at it
    household_age_list = list(
        household.get("people", {}).get("you", {}).get("age", {}).keys()
    )
    # If it is, overwrite household_year with the value present
    if len(household_age_list) > 0:
        household_year = household_age_list[0]

    return household_year