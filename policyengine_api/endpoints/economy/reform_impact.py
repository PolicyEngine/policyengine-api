from policyengine_api.data.v1_daos import runtime_v1_unit_of_work


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
    with runtime_v1_unit_of_work(local=True).transaction() as repositories:
        repositories.reform_impacts.set_message(
            comment,
            country_id=country_id,
            reform_policy_id=policy_id,
            baseline_policy_id=baseline_policy_id,
            region=region,
            time_period=time_period,
            options_hash=options_hash,
            dataset=dataset,
        )
