from policyengine_api.country import COUNTRIES, validate_country
from policyengine_api.data import database
from policyengine_api.utils import hash_object
from policyengine_api.constants import VERSION, COUNTRY_PACKAGE_VERSIONS
from policyengine_core.reforms import Reform
from policyengine_core.parameters import ParameterNode, Parameter
from policyengine_core.periods import instant
import json


def get_policy(
    country_id: str, policy_id: int = None, policy_data: dict = None
) -> dict:
    """
    Get policy data for a given country and policy ID, or get the full record for a given policy from its data.

    Args:
        country_id (str): The country ID.
        policy_id (int, optional): The policy ID. Defaults to None.
        policy_data (dict, optional): The policy data. Defaults to None.

    Returns:
        dict: The policy record.
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    policy = None
    if policy_id is not None:
        # Get the policy record for a given policy ID.
        policy = database.get_in_table(
            "policy", country_id=country_id, id=policy_id
        )
        if policy is None:
            return dict(
                status="error",
                message=f"Policy {policy_id} not found in {country_id}",
            )
    elif policy_data is not None:
        # Get the policy record for a given policy data object.
        policy = database.get_in_table(
            "policy",
            country_id=country_id,
            policy_hash=hash_object(policy_data),
        )
        if policy is None:
            return dict(
                status="error",
                message=f"Policy not found in {country_id}",
            )
    else:
        return dict(
            status="error",
            message=f"Must provide either policy_id or policy_data",
        )
    policy = dict(policy)
    policy["policy_json"] = json.loads(policy["policy_json"])
    return dict(
        status="ok",
        message=None,
        result=policy,
    )


def set_policy(
    country_id: str, policy_id: str, policy_json: dict, label: str = None
) -> dict:
    """
    Set policy data for a given country and policy ID.

    Args:
        country_id (str): The country ID.
        policy_json (dict): The policy data.
        policy_id (str, optional): The policy ID. Defaults to None.
        label (str, optional): The policy label. Defaults to None.
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    policy_hash = hash_object(policy_json)
    match = dict(policy_hash=policy_hash)
    if policy_id is not None:
        match["id"] = policy_id
    # Don't allow changes to policies with IDs 1, 2, or 3.
    if policy_id in [1, 2, 3]:
        return dict(
            status="error",
            message=f"Cannot change policy with ID {policy_id}",
        )
    # Check if the policy already exists and has a label.
    existing_policy = database.get_in_table(
        "policy", country_id=country_id, policy_hash=policy_hash
    )
    if existing_policy is not None:
        if existing_policy["label"] is not None:
            # If the submitted policy JSON contains a label, check that it matches the existing label.
            if label is not None and label != existing_policy["label"]:
                return dict(
                    status="error",
                    message=f"Policy already exists with label {existing_policy['label']}. Once a policy has a label, it cannot be changed.",
                )
        else:
            policy_id = existing_policy["id"]
    database.set_in_table(
        "policy",
        match,
        dict(
            country_id=country_id,
            policy_json=json.dumps(policy_json),
            label=label,
            api_version=COUNTRY_PACKAGE_VERSIONS[country_id],
        ),
        auto_increment="id",
    )

    policy_id = database.get_in_table(
        "policy", country_id=country_id, policy_hash=policy_hash
    )["id"]
    return dict(
        status="ok",
        message=None,
        result=dict(
            policy_id=policy_id,
        ),
    )


def create_policy_reform(country_id: str, policy_data: dict) -> dict:
    """
    Create a policy reform.

    Args:
        country_id (str): The country ID.
        policy_data (dict): The policy data.

    Returns:
        dict: The reform.
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    def modify_parameters(parameters: ParameterNode) -> ParameterNode:
        for path, values in policy_data.items():
            node = parameters
            for step in path.split("."):
                if "[" in step:
                    step, index = step.split("[")
                    index = int(index[:-1])
                    node = node.children[step].brackets[index]
                else:
                    node = node.children[step]
            for period, value in values.items():
                start, end = period.split(".")
                node_type = type(node.values_list[-1].value)
                if node_type == int:
                    node_type = float  # '0' is of type int by default, but usually we want to cast to float.
                node.update(
                    start=instant(start),
                    stop=instant(end),
                    value=node_type(value),
                )

        return parameters

    class reform(Reform):
        def apply(self):
            self.modify_parameters(modify_parameters)

    return reform


def search_policies(country_id: str, query: str) -> list:
    """
    Search for policies.

    Args:
        country_id (str): The country ID.
        query (str): The search query.

    Returns:
        list: The search results.
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    results = database.query(
        "SELECT id, label FROM policy WHERE country_id = ? AND label LIKE ?",
        (country_id, f"%{query}%"),
    )
    if results is None:
        return dict(
            status="error",
            message=f"Policy not found in {country_id}",
        )
    else:
        results = results.fetchall()
    # Format into: [{ id: 1, label: "My policy" }, ...]
    policies = [dict(id=result[0], label=result[1]) for result in results]
    return dict(
        status="ok",
        message=None,
        result=policies,
    )


def get_current_law_policy_id(country_id: str) -> int:
    policy_hash = hash_object({})
    return database.query(
        "SELECT id FROM policy WHERE country_id = ? AND policy_hash = ?",
        (country_id, policy_hash),
    ).fetchone()[0]
