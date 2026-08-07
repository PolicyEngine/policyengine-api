from policyengine_api.utils.payload_validators import validate_country
import json
from flask import Response, request
from sqlalchemy import select

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Policy, UserPolicy


USER_POLICY_IDENTITY_FIELDS = (
    "country_id",
    "reform_id",
    "baseline_id",
    "user_id",
    "year",
    "geography",
    "reform_label",
    "baseline_label",
    "dataset",
)


def _serialize_user_policy(user_policy: UserPolicy) -> dict:
    return {
        column.name: getattr(user_policy, column.name)
        for column in UserPolicy.__table__.columns
    }


@validate_country
def get_policy_search(country_id: str) -> dict:
    """
    Search for policies for a specified country

    Args:
        country_id (str): The country ID.

    Query Parameters:
        query (str): Optional search term to filter policies
        unique_only (bool): If true, return only unique policy-label combinations

    Returns:
        Response: Json response with:
            - On success: list of policies with id and label
            - On failure: error message and appropriate status code

    Example:
        GET /api/policies/us?query=tax&unique_only=true
    """

    query = request.args.get("query", "")
    # The "json.loads" default type is added to convert lowercase
    # "true" and "false" to Python-friendly bool values
    unique_only = request.args.get("unique_only", default=False, type=json.loads)

    try:
        with get_v1_session_factory()() as session:
            results = session.scalars(
                select(Policy).where(
                    Policy.country_id == country_id,
                    Policy.label.contains(query, autoescape=True),
                )
            ).all()

        if not results:
            body = dict(
                status="error",
                message=f"No policies found for country {country_id} for query '{query}",
            )
            return Response(json.dumps(body), status=404, mimetype="application/json")

        # If unique_only is true, filter results to only include
        # items where everything except ID is unique
        if unique_only:
            processed_vals = set()
            new_results = []

            # Compare every label and hash to what's contained in processed_vals
            # If a label-hash set aren't already in processed_vals,
            # add them to new_results
            for policy in results:
                comparison_vals = policy.label, policy.policy_hash
                if comparison_vals not in processed_vals:
                    new_results.append(policy)
                    processed_vals.add(comparison_vals)

            # Overwrite results with new_results
            results = new_results

        # Format into: [{ id: 1, label: "My policy" }, ...]
        policies = [dict(id=result.id, label=result.label) for result in results]
        body = dict(
            status="ok",
            message="Policies found",
            result=policies,
        )
        return Response(json.dumps(body), status=200, mimetype="application/json")
    except Exception as e:
        body = dict(status="error", message=f"Internal server error: {e}")
        return Response(json.dumps(body), status=500, mimetype="application/json")


@validate_country
def set_user_policy(country_id: str) -> dict:
    """
    Adds a record (if unique, barring type) to the user_policy table
    that defines a particular policy as saved by a user to "their
    policies"; this table also contains an optional "type" column that
    is currently unused
    """

    payload = request.json
    reform_label = payload.pop("reform_label", None)
    reform_id = payload.pop("reform_id")
    baseline_label = payload.pop("baseline_label", None)
    baseline_id = payload.pop("baseline_id")
    user_id = payload.pop("user_id")
    year = payload.pop("year")
    geography = payload.pop("geography")
    dataset = payload.pop("dataset", None)
    number_of_provisions = payload.pop("number_of_provisions")
    api_version = payload.pop("api_version")
    added_date = payload.pop("added_date")
    updated_date = payload.pop("updated_date")
    budgetary_impact = payload.pop("budgetary_impact", None)
    type = payload.pop("type", None)

    values = {
        "country_id": country_id,
        "reform_id": reform_id,
        "reform_label": reform_label,
        "baseline_id": baseline_id,
        "baseline_label": baseline_label,
        "user_id": user_id,
        "year": year,
        "geography": geography,
        "dataset": dataset,
        "number_of_provisions": number_of_provisions,
        "api_version": api_version,
        "added_date": added_date,
        "updated_date": updated_date,
        "budgetary_impact": budgetary_impact,
        "type": type,
    }

    # When setting a user policy, "unique" records contain
    # a unique set of the following pieces of data:
    # country_id, reform_id, baseline_id, user_id, year,
    # geography, reform_label, baseline_label, dataset;
    # added_date, budgetary_impact, updated_date,
    # number_of_provisions, and api_version are
    # all changeable, and thus do not need
    # to be tested; type is not yet implemented

    try:
        with get_v1_session_factory().begin() as session:
            user_policy = session.scalar(
                select(UserPolicy).where(
                    *(
                        getattr(UserPolicy, field) == values[field]
                        for field in USER_POLICY_IDENTITY_FIELDS
                    )
                )
            )
            if user_policy is None:
                user_policy = UserPolicy(**values)
                session.add(user_policy)
                session.flush()
            else:
                response = dict(
                    status="ok",
                    message=f"The reform #{reform_id} / baseline #{baseline_id} pair already exists for user {user_id}",
                    result=dict(id=user_policy.id),
                )
                return Response(
                    json.dumps(response),
                    status=200,
                    mimetype="application/json",
                )
    except Exception as e:
        return Response(
            json.dumps(
                {"message": f"Internal database error: {e}; please try again later."}
            ),
            status=500,
            mimetype="application/json",
        )

    response_body = dict(
        status="ok",
        message="Record created successfully",
        result=dict(
            **_serialize_user_policy(user_policy),
        ),
    )

    return Response(
        json.dumps(response_body),
        status=201,
        mimetype="application/json",
    )


@validate_country
def get_user_policy(country_id: str, user_id: str) -> dict:
    """
    Fetch all saved user policies by user id
    """

    # Get the policy record for a given policy ID.
    with get_v1_session_factory()() as session:
        user_policies = session.scalars(
            select(UserPolicy).where(
                UserPolicy.country_id == country_id,
                UserPolicy.user_id == user_id,
            )
        ).all()

        rows_parsed = [_serialize_user_policy(row) for row in user_policies]

    if rows_parsed is None:
        response = dict(
            status="ok",
            message=f"No saved policies found for user {user_id}",
        )
        return Response(
            json.dumps(response),
            status=200,
            mimetype="application/json",
        )
    return dict(
        status="ok",
        message=None,
        result=rows_parsed,
    )


# Whitelist of columns that callers are allowed to modify via
# update_user_policy. Identity columns (id, country_id, user_id,
# reform_id, baseline_id) are intentionally excluded because they
# define the record; allowing clients to rewrite them would both
# break referential assumptions and let the column name be used
# as a SQL injection vector (keys are interpolated into the
# UPDATE statement below).
UPDATE_USER_POLICY_ALLOWED_FIELDS = frozenset(
    {
        "reform_label",
        "baseline_label",
        "year",
        "geography",
        "dataset",
        "number_of_provisions",
        "api_version",
        "added_date",
        "updated_date",
        "budgetary_impact",
        "type",
    }
)


@validate_country
def update_user_policy(country_id: str) -> dict:
    """
    Update any parts of a user_policy, given a user_policy ID
    """

    payload = request.json
    if not isinstance(payload, dict) or "id" not in payload:
        return Response(
            json.dumps({"message": "Request body must include an 'id' field."}),
            status=400,
            mimetype="application/json",
        )

    user_policy_id = payload.pop("id")

    # Reject any unknown/unsafe keys. The keys end up interpolated
    # into a SQL UPDATE statement, so we must validate them against
    # a static whitelist instead of trusting the JSON payload.
    unknown_keys = [
        key for key in payload if key not in UPDATE_USER_POLICY_ALLOWED_FIELDS
    ]
    if unknown_keys:
        return Response(
            json.dumps(
                {
                    "message": (
                        "Request body contains unsupported fields: "
                        f"{sorted(unknown_keys)}"
                    )
                }
            ),
            status=400,
            mimetype="application/json",
        )

    if not payload:
        return Response(
            json.dumps(
                {"message": "Request body must include at least one field to update."}
            ),
            status=400,
            mimetype="application/json",
        )

    try:
        with get_v1_session_factory().begin() as session:
            user_policy = session.get(UserPolicy, user_policy_id)
            if user_policy is not None:
                for key, value in payload.items():
                    setattr(user_policy, key, value)
    except Exception as e:
        return Response(
            json.dumps(
                {"message": f"Internal database error: {e}; please try again later."}
            ),
            status=500,
            mimetype="application/json",
        )

    response_body = dict(
        status="ok",
        message="Record updated successfully",
        result=dict(id=user_policy_id),
    )

    return Response(
        json.dumps(response_body),
        status=200,
        mimetype="application/json",
    )
