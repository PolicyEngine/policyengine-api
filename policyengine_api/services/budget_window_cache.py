import hashlib
import json
import os
from typing import Any

import redis

from policyengine_api.gcp_logging import logger

BUDGET_WINDOW_CACHE_PREFIX = "budget_window:v1"
BUDGET_WINDOW_STARTING_PREFIX = "starting:"
BUDGET_WINDOW_STARTING_TTL_SECONDS = int(
    os.environ.get("BUDGET_WINDOW_STARTING_TTL_SECONDS", "300")
)
BUDGET_WINDOW_BATCH_TTL_SECONDS = int(
    os.environ.get("BUDGET_WINDOW_BATCH_TTL_SECONDS", "86400")
)
BUDGET_WINDOW_RESULT_TTL_SECONDS = int(
    os.environ.get("BUDGET_WINDOW_RESULT_TTL_SECONDS", "2592000")
)


class BudgetWindowCache:
    """Redis-backed cache and in-flight mapping for budget-window requests."""

    def __init__(self, client: redis.Redis | None = None):
        self._client = client

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis(
                host=os.environ.get("CACHE_REDIS_HOST", "127.0.0.1"),
                port=int(os.environ.get("CACHE_REDIS_PORT", "6379")),
                db=int(os.environ.get("CACHE_REDIS_DB", "0")),
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        return self._client

    def build_key(
        self,
        *,
        country_id: str,
        reform_policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str | None,
        api_version: str,
    ) -> str:
        key_payload = {
            "country_id": country_id,
            "reform_policy_id": reform_policy_id,
            "baseline_policy_id": baseline_policy_id,
            "region": region,
            "dataset": dataset,
            "time_period": time_period,
            "options_hash": options_hash,
            "api_version": api_version,
        }
        encoded = json.dumps(
            key_payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"{BUDGET_WINDOW_CACHE_PREFIX}:{country_id}:{digest}"

    def _result_key(self, cache_key: str) -> str:
        return f"{cache_key}:result"

    def _batch_key(self, cache_key: str) -> str:
        return f"{cache_key}:batch_job_id"

    def _handle_cache_error(self, operation: str, error: Exception) -> None:
        logger.log_struct(
            {
                "message": f"Budget-window Redis cache {operation} failed",
                "error": str(error),
            },
            severity="WARNING",
        )

    def get_completed_result(self, cache_key: str) -> dict[str, Any] | None:
        try:
            payload = self.client.get(self._result_key(cache_key))
        except Exception as error:
            self._handle_cache_error("read", error)
            raise

        if not payload:
            return None

        try:
            result = json.loads(payload)
        except (TypeError, ValueError) as error:
            self._handle_cache_error("decode", error)
            return None

        return result if isinstance(result, dict) else None

    def set_completed_result(self, cache_key: str, result: dict[str, Any]) -> None:
        try:
            self.client.set(
                self._result_key(cache_key),
                json.dumps(result),
                ex=BUDGET_WINDOW_RESULT_TTL_SECONDS,
            )
        except Exception as error:
            self._handle_cache_error("write result", error)

    def get_batch_job_id(self, cache_key: str) -> str | None:
        try:
            value = self.client.get(self._batch_key(cache_key))
        except Exception as error:
            self._handle_cache_error("read batch id", error)
            raise

        if not isinstance(value, str) or not value:
            return None
        if value.startswith(BUDGET_WINDOW_STARTING_PREFIX):
            return None
        return value

    def claim_batch_start(self, cache_key: str, claim_token: str) -> bool:
        try:
            claimed = self.client.set(
                self._batch_key(cache_key),
                f"{BUDGET_WINDOW_STARTING_PREFIX}{claim_token}",
                nx=True,
                ex=BUDGET_WINDOW_STARTING_TTL_SECONDS,
            )
        except Exception as error:
            self._handle_cache_error("claim", error)
            raise

        return bool(claimed)

    def store_batch_job_id(self, cache_key: str, batch_job_id: str) -> None:
        try:
            self.client.set(
                self._batch_key(cache_key),
                batch_job_id,
                ex=BUDGET_WINDOW_BATCH_TTL_SECONDS,
            )
        except Exception as error:
            self._handle_cache_error("write batch id", error)
            raise

    def clear_starting_claim(self, cache_key: str, claim_token: str) -> None:
        try:
            batch_key = self._batch_key(cache_key)
            value = self.client.get(batch_key)
            if value == f"{BUDGET_WINDOW_STARTING_PREFIX}{claim_token}":
                self.client.delete(batch_key)
        except Exception as error:
            self._handle_cache_error("clear claim", error)

    def clear_batch_job_id(self, cache_key: str) -> None:
        try:
            self.client.delete(self._batch_key(cache_key))
        except Exception as error:
            self._handle_cache_error("clear batch id", error)
