"""Validate calculate payload input names before simulation creation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UnrecognizedInput:
    """One payload name the country model does not recognise, and where it appears.

    The entity plurals are set only for a variable placed on the wrong entity.
    """

    input_type: str
    name: str
    path: str
    expected_entity_plural: str | None = None
    actual_entity_plural: str | None = None

    @property
    def message(self) -> str:
        """A one-sentence, user-facing description of the problem and where it is."""
        if self.input_type == "household_entity":
            return (
                f"Unrecognized household entity group `{self.name}` at `{self.path}`."
            )
        if self.input_type == "household_variable_wrong_entity":
            return (
                f"Household variable `{self.name}` belongs on "
                f"`{self.expected_entity_plural}`, not `{self.actual_entity_plural}`, "
                f"at `{self.path}`."
            )
        if self.input_type == "household_axis_variable":
            return (
                f"Unrecognized household axis variable `{self.name}` at `{self.path}`."
            )
        if self.input_type == "policy_parameter":
            return f"Unrecognized policy parameter `{self.name}` at `{self.path}`."
        return f"Unrecognized household variable `{self.name}` at `{self.path}`."

    def to_dict(self) -> dict:
        """Return the JSON error entry, omitting entity plurals that are not set."""
        data = {
            "type": self.input_type,
            "name": self.name,
            "path": self.path,
            "message": self.message,
        }
        if self.expected_entity_plural is not None:
            data["expected_entity_plural"] = self.expected_entity_plural
        if self.actual_entity_plural is not None:
            data["actual_entity_plural"] = self.actual_entity_plural
        return data


def find_unrecognized_inputs(
    household: dict,
    policy: dict,
    metadata: dict,
) -> list[UnrecognizedInput]:
    """Return calculate payload names that the country package cannot resolve."""
    return [
        *find_unrecognized_household_inputs(household, metadata),
        *find_unrecognized_policy_inputs(policy, metadata),
    ]


def find_unrecognized_household_inputs(
    household: dict,
    metadata: dict,
) -> list[UnrecognizedInput]:
    """Find unknown entity groups, variables and axis variables in a household.

    Also reports a known variable placed on the wrong entity. Role membership
    keys (such as ``members``) are not variables and are skipped, as are
    sections that are not objects.
    """
    if not isinstance(household, dict):
        return []

    errors: list[UnrecognizedInput] = []
    variables = metadata.get("variables", {})
    entities = metadata.get("entities", {})
    entity_by_plural = {
        entity["plural"]: entity for entity in entities.values() if "plural" in entity
    }

    for entity_plural, entity_group in household.items():
        if entity_plural == "axes":
            errors.extend(_find_unrecognized_axes(entity_group, variables))
            continue

        entity = entity_by_plural.get(entity_plural)
        if entity is None:
            errors.append(
                UnrecognizedInput(
                    input_type="household_entity",
                    name=entity_plural,
                    path=f"household.{entity_plural}",
                )
            )
            continue
        if not isinstance(entity_group, dict):
            continue

        errors.extend(
            _find_unrecognized_entity_inputs(
                entity_plural,
                entity_group,
                entity,
                variables,
                entities,
            )
        )

    return errors


def _find_unrecognized_entity_inputs(
    entity_plural: str,
    entity_group: dict,
    entity: dict,
    variables: dict,
    entities: dict,
) -> list[UnrecognizedInput]:
    """Find unknown and misplaced variables in one entity group's members.

    Role membership keys and members that are not objects are skipped.
    """
    relationship_keys = {
        role["plural"] for role in entity.get("roles", {}).values() if "plural" in role
    }
    errors: list[UnrecognizedInput] = []
    for entity_id, entity_inputs in entity_group.items():
        if not isinstance(entity_inputs, dict):
            continue
        for variable_name in entity_inputs:
            if variable_name in relationship_keys:
                continue
            error = _unrecognized_variable(
                variable_name,
                path=f"household.{entity_plural}.{entity_id}.{variable_name}",
                entity_plural=entity_plural,
                variables=variables,
                entities=entities,
            )
            if error is not None:
                errors.append(error)
    return errors


def _unrecognized_variable(
    variable_name: str,
    *,
    path: str,
    entity_plural: str,
    variables: dict,
    entities: dict,
) -> UnrecognizedInput | None:
    """Report a variable the model lacks or that belongs on another entity, if so."""
    variable = variables.get(variable_name)
    if variable is None:
        return UnrecognizedInput(
            input_type="household_variable",
            name=variable_name,
            path=path,
        )
    expected_entity = entities.get(variable["entity"], {})
    expected_entity_plural = expected_entity.get("plural")
    if expected_entity_plural is not None and expected_entity_plural != entity_plural:
        return UnrecognizedInput(
            input_type="household_variable_wrong_entity",
            name=variable_name,
            path=path,
            expected_entity_plural=expected_entity_plural,
            actual_entity_plural=entity_plural,
        )
    return None


def find_unrecognized_policy_inputs(
    policy: dict,
    metadata: dict,
) -> list[UnrecognizedInput]:
    """Find policy keys that are not parameters in the country metadata."""
    if not isinstance(policy, dict):
        return []

    parameters = metadata.get("parameters", {})
    return [
        UnrecognizedInput(
            input_type="policy_parameter",
            name=parameter_name,
            path=f"policy.{parameter_name}",
        )
        for parameter_name in policy
        if parameter_name not in parameters
    ]


def format_unrecognized_inputs_message(errors: list[UnrecognizedInput]) -> str:
    """Join the problems' messages into one error message for the response."""
    return "Unrecognized calculate input(s): " + "; ".join(
        error.message for error in errors
    )


def _find_unrecognized_axes(axes: object, variables: dict) -> list[UnrecognizedInput]:
    if not isinstance(axes, list):
        return []

    errors: list[UnrecognizedInput] = []
    for entry_index, entry in enumerate(axes):
        if isinstance(entry, list):
            for axis_index, axis in enumerate(entry):
                errors.extend(
                    _find_unrecognized_axis(
                        axis,
                        f"household.axes[{entry_index}][{axis_index}].name",
                        variables,
                    )
                )
            continue
        errors.extend(
            _find_unrecognized_axis(
                entry,
                f"household.axes[{entry_index}].name",
                variables,
            )
        )
    return errors


def _find_unrecognized_axis(
    axis: object,
    path: str,
    variables: dict,
) -> list[UnrecognizedInput]:
    if not isinstance(axis, dict) or "name" not in axis:
        return []

    variable_name = axis["name"]
    if variable_name in variables:
        return []
    return [
        UnrecognizedInput(
            input_type="household_axis_variable",
            name=variable_name,
            path=path,
        )
    ]
