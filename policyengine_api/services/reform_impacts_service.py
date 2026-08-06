import datetime

from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import ReformImpactDAO


class ReformImpactsService:
    def __init__(self, impacts: ReformImpactDAO | None = None):
        self._impacts = impacts

    @property
    def impacts(self) -> ReformImpactDAO:
        if self._impacts is None:
            self._impacts = ReformImpactDAO(build_v1_session_manager())
        return self._impacts

    @staticmethod
    def _filters(
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        api_version=None,
    ):
        filters = {
            "country_id": country_id,
            "reform_policy_id": policy_id,
            "baseline_policy_id": baseline_policy_id,
            "region": region,
            "dataset": dataset,
            "time_period": time_period,
        }
        if api_version is not None:
            filters["api_version"] = api_version
        return filters

    def get_all_reform_impacts(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        api_version,
    ):
        return self.impacts.list(
            **self._filters(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                api_version,
            ),
            options_hash=options_hash,
        )

    def get_all_reform_impacts_by_options_hash_prefix(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        options_hash_prefix,
        api_version,
    ):
        return self.impacts.list_by_options_hash(
            options_hash,
            options_hash_prefix,
            **self._filters(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                api_version,
            ),
        )

    def set_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options,
        options_hash,
        status,
        api_version,
        reform_impact_json,
        start_time,
        execution_id: str,
    ):
        return self.impacts.create(
            country_id=country_id,
            reform_policy_id=policy_id,
            baseline_policy_id=baseline_policy_id,
            region=region,
            dataset=dataset,
            time_period=time_period,
            options_json=options,
            options_hash=options_hash,
            status=status,
            api_version=api_version,
            reform_impact_json=reform_impact_json,
            start_time=start_time,
            execution_id=execution_id,
        )

    def delete_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
    ):
        self.impacts.delete_computing(
            **self._filters(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
            ),
            options_hash=options_hash,
        )

    def set_error_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        message,
        execution_id: str,
    ):
        del (
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
            options_hash,
        )
        return self.impacts.fail(execution_id, message, self._now())

    def set_complete_reform_impact(
        self,
        country_id,
        reform_policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        reform_impact_json,
        execution_id,
    ):
        del (
            country_id,
            reform_policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
            options_hash,
        )
        return self.impacts.complete(execution_id, reform_impact_json, self._now())

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
