from policyengine_api.data import local_database


def set_comment_on_job(
    comment: str,
    country_id,
    policy_id,
    baseline_policy_id,
    region,
    dataset,
    time_period,
    options_hash,
):
    query = (
        "UPDATE reform_impact SET message = ? WHERE country_id = ? AND "
        "reform_policy_id = ? AND baseline_policy_id = ? AND region = ? AND "
        "time_period = ? AND options_hash = ? AND dataset = ?"
    )

    local_database.query(
        query,
        (
            comment,
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            time_period,
            options_hash,
            dataset,
        ),
    )
