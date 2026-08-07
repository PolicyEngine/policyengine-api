from sqlalchemy import select

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import ReformImpact


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
    with get_v1_session_factory(local=True).begin() as session:
        impacts = session.scalars(
            select(ReformImpact).where(
                ReformImpact.country_id == country_id,
                ReformImpact.reform_policy_id == policy_id,
                ReformImpact.baseline_policy_id == baseline_policy_id,
                ReformImpact.region == region,
                ReformImpact.time_period == time_period,
                ReformImpact.options_hash == options_hash,
                ReformImpact.dataset == dataset,
            )
        )
        for impact in impacts:
            impact.message = comment
