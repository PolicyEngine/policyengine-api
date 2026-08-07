import datetime
from contextlib import contextmanager
from typing import Any

from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import ReformImpactDAO, V1UnitOfWork


class ReformImpactsService:
    def __init__(
        self,
        impacts: ReformImpactDAO | None = None,
        *,
        unit_of_work: V1UnitOfWork | None = None,
    ):
        self._impacts = impacts
        self._unit_of_work = unit_of_work

    @property
    def unit_of_work(self) -> V1UnitOfWork:
        if self._unit_of_work is None:
            self._unit_of_work = V1UnitOfWork(build_v1_session_manager(local=True))
        return self._unit_of_work

    @contextmanager
    def _repository(self, *, write: bool = False):
        if self._impacts is not None:
            yield self._impacts
            return
        boundary = self.unit_of_work.transaction if write else self.unit_of_work.read
        with boundary() as daos:
            yield daos.reform_impacts

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
        with self._repository() as impacts:
            return impacts.list(
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
        with self._repository() as impacts:
            return impacts.list_by_options_hash(
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
        options: dict[str, Any],
        options_hash,
        status,
        api_version,
        reform_impact_json: dict[str, Any],
        start_time,
        execution_id: str,
    ):
        with self._repository(write=True) as impacts:
            return impacts.create(
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
        with self._repository(write=True) as impacts:
            impacts.delete_computing(
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
        with self._repository(write=True) as impacts:
            return impacts.fail(execution_id, message, self._now())

    def set_complete_reform_impact(
        self,
        country_id,
        reform_policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        reform_impact_json: dict[str, Any],
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
        with self._repository(write=True) as impacts:
            return impacts.complete(execution_id, reform_impact_json, self._now())

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
