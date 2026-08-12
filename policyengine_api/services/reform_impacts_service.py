import datetime
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import ReformImpact


class ReformImpactsService:
    """Reform-impact operations with service-owned local transactions."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._injected_session_factory = session_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory(local=True)

    def get_recent_reform_impacts(self, max_results: int) -> list[ReformImpact]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(ReformImpact)
                    .order_by(ReformImpact.start_time.desc())
                    .limit(max_results)
                )
            )

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
    ) -> list[ReformImpact]:
        with self._sessions() as session:
            return self._get_all_reform_impacts(
                session,
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                api_version,
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
    ) -> list[ReformImpact]:
        with self._sessions() as session:
            return self._get_all_reform_impacts_by_options_hash_prefix(
                session,
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                options_hash_prefix,
                api_version,
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
    ) -> ReformImpact:
        with self._sessions.begin() as session:
            return self._set_reform_impact(
                session,
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
                execution_id,
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
    ) -> None:
        with self._sessions.begin() as session:
            self._delete_reform_impact(
                session,
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
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
    ) -> ReformImpact | None:
        with self._sessions.begin() as session:
            return self._set_error_reform_impact(
                session,
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                message,
                execution_id,
            )

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
    ) -> ReformImpact | None:
        with self._sessions.begin() as session:
            return self._set_complete_reform_impact(
                session,
                country_id,
                reform_policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                reform_impact_json,
                execution_id,
            )

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

    @staticmethod
    def _scope(statement, **filters):
        return statement.where(
            *(getattr(ReformImpact, key) == value for key, value in filters.items())
        )

    def _get_all_reform_impacts(
        self,
        session: Session,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        api_version,
    ) -> list[ReformImpact]:
        filters = self._filters(
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
            api_version,
        )
        statement = self._scope(select(ReformImpact), **filters).where(
            ReformImpact.options_hash == options_hash
        )
        return list(session.scalars(statement.order_by(ReformImpact.start_time.desc())))

    def _get_all_reform_impacts_by_options_hash_prefix(
        self,
        session: Session,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        options_hash_prefix,
        api_version,
    ) -> list[ReformImpact]:
        filters = self._filters(
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
            api_version,
        )
        statement = self._scope(select(ReformImpact), **filters).where(
            or_(
                ReformImpact.options_hash == options_hash,
                ReformImpact.options_hash.like(options_hash_prefix, escape="\\"),
            )
        )
        return list(
            session.scalars(
                statement.order_by(
                    (ReformImpact.options_hash == options_hash).desc(),
                    ReformImpact.start_time.desc(),
                )
            )
        )

    def _set_reform_impact(
        self,
        session: Session,
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
    ) -> ReformImpact:
        impact = ReformImpact(
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
        session.add(impact)
        session.flush()
        return impact

    def _delete_reform_impact(
        self,
        session: Session,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
    ) -> None:
        filters = self._filters(
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
        )
        session.execute(
            self._scope(delete(ReformImpact), **filters).where(
                ReformImpact.options_hash == options_hash,
                ReformImpact.status == "computing",
            )
        )

    def _set_error_reform_impact(
        self,
        session: Session,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        message,
        execution_id: str,
    ) -> ReformImpact | None:
        del (
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
            options_hash,
        )
        impact = session.scalar(
            select(ReformImpact)
            .where(ReformImpact.execution_id == execution_id)
            .order_by(ReformImpact.reform_impact_id.desc())
        )
        if impact is None:
            return None
        impact.status = "error"
        impact.message = message
        impact.end_time = self._now()
        return impact

    def _set_complete_reform_impact(
        self,
        session: Session,
        country_id,
        reform_policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        reform_impact_json: dict[str, Any],
        execution_id,
    ) -> ReformImpact | None:
        del (
            country_id,
            reform_policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
            options_hash,
        )
        impact = session.scalar(
            select(ReformImpact)
            .where(ReformImpact.execution_id == execution_id)
            .order_by(ReformImpact.reform_impact_id.desc())
        )
        if impact is None:
            return None
        impact.status = "ok"
        impact.message = "Completed"
        impact.reform_impact_json = reform_impact_json
        impact.end_time = self._now()
        return impact

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
