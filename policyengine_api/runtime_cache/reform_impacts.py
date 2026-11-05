"""Recoverable reform-impact caching and submission coordination."""

import hashlib
import math
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError

from policyengine_api.observability.identifiers import normalize_observability_id
from policyengine_api.runtime_cache.claims import ExpiringClaimStore
from policyengine_api.runtime_cache.core import (
    PTTL_NO_EXPIRY,
    CacheBackend,
    CacheCoordinationError,
    CacheNamespace,
    decode_envelope,
    encode_envelope,
    jittered_ttl,
    record_cache_event,
)

REFORM_IMPACT_SCHEMA_VERSION = 3
REFORM_IMPACT_TTL_SECONDS = 2_592_000
REFORM_IMPACT_INDEX_LIMIT = 1_000
REFORM_IMPACT_START_CLAIM_TTL_SECONDS = 300
REFORM_IMPACT_START_CLAIM_FAMILY = "reform-impact-start-claim"
# Whether index lookups in the current context raise, rather than read as
# empty, when the cache cannot be read (see ReformImpactCache.reads_fail_closed).
_LOOKUPS_FAIL_CLOSED: ContextVar[bool] = ContextVar(
    "reform_impact_lookups_fail_closed", default=False
)
# Remove a record (KEYS[1]) and its entries in the scope and recent indexes
# (KEYS[2], KEYS[3]) only if the record still holds exactly ARGV[1], the value
# the caller read and checked. One script, so nothing can rewrite the record
# between the comparison and the removal.
DELETE_UNCHANGED_RECORD = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  redis.call('del', KEYS[1])
  redis.call('zrem', KEYS[2], KEYS[1])
  redis.call('zrem', KEYS[3], KEYS[1])
  return 1
end
return 0
""".strip()


@dataclass(frozen=True)
class ReformImpactStartClaim:
    """Atomic ownership and diagnostic context for one job submission."""

    submission_claim_id: str
    observability_id: str

    def to_payload(self) -> dict[str, str]:
        """Return the JSON object stored as the claim's value."""
        return {
            "submission_claim_id": self.submission_claim_id,
            "observability_id": self.observability_id,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "ReformImpactStartClaim | None":
        """Rebuild a claim, or return None if a field is missing or invalid."""
        if not isinstance(payload, dict):
            return None
        submission_claim_id = payload.get("submission_claim_id")
        if not isinstance(submission_claim_id, str) or not submission_claim_id:
            return None
        observability_id = normalize_observability_id(payload.get("observability_id"))
        if observability_id is None:
            return None
        return cls(
            submission_claim_id=submission_claim_id,
            observability_id=observability_id,
        )


@dataclass(frozen=True)
class ReformImpactScope:
    """The policy pair, region, dataset and period a reform impact is computed for."""

    country_id: str
    reform_policy_id: int
    baseline_policy_id: int
    region: str
    dataset: str
    time_period: str


@dataclass(frozen=True)
class ReformImpactIdentity:
    """Everything that identifies one cached reform impact calculation.

    ``api_version`` is the cache generation and ``options_hash`` identifies the
    calculation options and runtime bundle.
    """

    scope: ReformImpactScope
    api_version: str
    options_hash: str | None


@dataclass(frozen=True)
class CachedReformImpact:
    """An economy-impact job and its result, shaped like a legacy reform_impact row.

    ``status`` is ``computing``, ``ok`` or ``error``; naive datetimes are UTC.
    """

    reform_impact_id: int
    baseline_policy_id: int
    reform_policy_id: int
    country_id: str
    region: str
    dataset: str
    time_period: str
    options_json: dict[str, Any] | None
    options_hash: str | None
    api_version: str
    reform_impact_json: dict[str, Any]
    status: str
    message: str | None
    start_time: datetime | None
    end_time: datetime | None
    execution_id: str | None
    error_code: str | None = None
    observability_id: str | None = None


def _datetime_to_wire(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _datetime_from_wire(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        msg = "invalid cached datetime"
        raise TypeError(msg)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _impact_to_wire(impact: CachedReformImpact) -> dict[str, Any]:
    values = asdict(impact)
    values["start_time"] = _datetime_to_wire(impact.start_time)
    values["end_time"] = _datetime_to_wire(impact.end_time)
    return values


def _impact_from_wire(payload: object) -> CachedReformImpact | None:
    if not isinstance(payload, dict):
        return None
    try:
        return CachedReformImpact(
            reform_impact_id=int(payload["reform_impact_id"]),
            baseline_policy_id=int(payload["baseline_policy_id"]),
            reform_policy_id=int(payload["reform_policy_id"]),
            country_id=str(payload["country_id"]),
            region=str(payload["region"]),
            dataset=str(payload["dataset"]),
            time_period=str(payload["time_period"]),
            options_json=payload.get("options_json"),
            options_hash=payload.get("options_hash"),
            api_version=str(payload["api_version"]),
            reform_impact_json=payload["reform_impact_json"],
            status=str(payload["status"]),
            message=payload.get("message"),
            start_time=_datetime_from_wire(payload.get("start_time")),
            end_time=_datetime_from_wire(payload.get("end_time")),
            execution_id=(
                str(payload["execution_id"])
                if payload["execution_id"] is not None
                else None
            ),
            error_code=payload.get("error_code"),
            observability_id=payload.get("observability_id"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _like_matches(value: str, pattern: str) -> bool:
    expression: list[str] = ["^"]
    escaped = False
    for character in pattern:
        if escaped:
            expression.append(re.escape(character))
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "%":
            expression.append(".*")
        elif character == "_":
            expression.append(".")
        else:
            expression.append(re.escape(character))
    if escaped:
        expression.append(re.escape("\\"))
    expression.append("$")
    return re.match("".join(expression), value) is not None


class ReformImpactCache:
    """Expiring reform-impact values with bounded expiring lookup indexes."""

    family = "reform-impact"

    def __init__(self, client: CacheBackend, namespace: CacheNamespace) -> None:
        """Keep values, indexes and start claims in ``client`` under ``namespace``."""
        self.client = client
        self.namespace = namespace
        self._start_claims = ExpiringClaimStore(client, family=self.family)

    def _start_claim_key(self, identity: ReformImpactIdentity, target: str) -> str:
        scope = identity.scope
        return self.namespace.key(
            REFORM_IMPACT_START_CLAIM_FAMILY,
            REFORM_IMPACT_SCHEMA_VERSION,
            {
                "api_version": identity.api_version,
                "baseline_policy_id": scope.baseline_policy_id,
                "country_id": scope.country_id,
                "dataset": scope.dataset,
                "options_hash": identity.options_hash,
                "reform_policy_id": scope.reform_policy_id,
                "region": scope.region,
                "target": target,
                "time_period": scope.time_period,
            },
        )

    @staticmethod
    def _encoded_start_claim(claim: ReformImpactStartClaim) -> str:
        return encode_envelope(
            REFORM_IMPACT_START_CLAIM_FAMILY,
            REFORM_IMPACT_SCHEMA_VERSION,
            claim.to_payload(),
        )

    def claim_start(
        self,
        identity: ReformImpactIdentity,
        *,
        target: str,
        claim_token: str,
        observability_id: str,
    ) -> bool:
        """Atomically claim ownership of one reform-impact submission."""
        claim = ReformImpactStartClaim.from_payload(
            {
                "submission_claim_id": claim_token,
                "observability_id": observability_id,
            }
        )
        if claim is None:
            msg = "a claim token and valid observability identifier are required"
            raise ValueError(msg)
        return self._start_claims.acquire(
            self._start_claim_key(identity, target),
            self._encoded_start_claim(claim),
            ttl_seconds=REFORM_IMPACT_START_CLAIM_TTL_SECONDS,
        )

    def get_start_claim(
        self,
        identity: ReformImpactIdentity,
        *,
        target: str,
    ) -> ReformImpactStartClaim | None:
        """Read the current submission owner and its diagnostic identifier."""
        started_at = time.perf_counter()
        key = self._start_claim_key(identity, target)
        try:
            encoded = self.client.get(key)
        except Exception as error:
            record_cache_event(
                family=self.family,
                event="coordination-failed",
                operation="claim-read",
                started_at=started_at,
                severity="WARNING",
            )
            msg = "reform-impact submission ownership is unavailable"
            raise CacheCoordinationError(msg) from error

        payload = decode_envelope(
            encoded,
            family=REFORM_IMPACT_START_CLAIM_FAMILY,
            schema_version=REFORM_IMPACT_SCHEMA_VERSION,
        )
        claim = ReformImpactStartClaim.from_payload(payload)
        if encoded is not None and claim is None:
            record_cache_event(
                family=self.family,
                event="decode-failed",
                operation="claim-read",
                started_at=started_at,
                severity="WARNING",
            )
            msg = "reform-impact submission ownership is unreadable"
            raise CacheCoordinationError(msg)

        record_cache_event(
            family=self.family,
            event="hit" if claim is not None else "miss",
            operation="claim-read",
            started_at=started_at,
        )
        return claim

    def release_start(
        self,
        identity: ReformImpactIdentity,
        *,
        target: str,
        claim_token: str,
        observability_id: str,
    ) -> bool:
        """Release a start claim only when its complete state still matches."""
        claim = ReformImpactStartClaim.from_payload(
            {
                "submission_claim_id": claim_token,
                "observability_id": observability_id,
            }
        )
        if claim is None:
            msg = "a claim token and valid observability identifier are required"
            raise ValueError(msg)

        return self._start_claims.release(
            self._start_claim_key(identity, target),
            self._encoded_start_claim(claim),
        )

    def _record_key(self, execution_id: str) -> str:
        return self.namespace.key(
            self.family,
            REFORM_IMPACT_SCHEMA_VERSION,
            {"execution_id": execution_id},
        )

    def _scope_index(self, impact: CachedReformImpact) -> str:
        return self.namespace.key(
            "reform-impact-index",
            REFORM_IMPACT_SCHEMA_VERSION,
            {
                "api_version": impact.api_version,
                "baseline_policy_id": impact.baseline_policy_id,
                "country_id": impact.country_id,
                "dataset": impact.dataset,
                "reform_policy_id": impact.reform_policy_id,
                "region": impact.region,
                "time_period": impact.time_period,
            },
        )

    def _recent_index(self) -> str:
        return self.namespace.family_key(
            "reform-impact-index",
            REFORM_IMPACT_SCHEMA_VERSION,
            "recent",
        )

    @staticmethod
    def _score(impact: CachedReformImpact) -> float:
        if impact.start_time is None:
            return time.time()
        value = impact.start_time
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.timestamp()

    def set(
        self,
        impact: CachedReformImpact,
        *,
        record_execution_id: str | None = None,
        record_ttl_seconds: int | None = None,
        only_if_present: bool = False,
    ) -> bool:
        """Store an impact and index it by scope and recency in one transaction.

        Each index keeps only the newest 1,000 entries. ``record_ttl_seconds``
        gives this record a shorter lifetime than the usual 30 days; the
        indexes keep theirs, and an index entry whose record has expired is
        skipped when read. ``only_if_present`` writes the record only if it
        still exists, so a write based on an earlier read never puts back a
        record that was deleted or expired since; the index entries it adds
        then point at no record and are skipped when read. Return False if
        the record was not written; raise ValueError when there is no record
        identifier.
        """
        # Terminal errors clear the worker handle in the payload while keeping
        # the original record key and lookup indexes stable.
        record_execution_id = record_execution_id or impact.execution_id
        if not record_execution_id:
            msg = "a reform-impact cache record identifier is required"
            raise ValueError(msg)
        record_key = self._record_key(record_execution_id)
        indexes = (self._scope_index(impact), self._recent_index())
        try:
            ttl_seconds = jittered_ttl(REFORM_IMPACT_TTL_SECONDS)
            with self.client.pipeline(transaction=True) as pipeline:
                pipeline.set(
                    record_key,
                    encode_envelope(
                        self.family,
                        REFORM_IMPACT_SCHEMA_VERSION,
                        _impact_to_wire(impact),
                    ),
                    ex=record_ttl_seconds or ttl_seconds,
                    # Redis's XX: write only a key that exists.
                    **({"xx": True} if only_if_present else {}),
                )
                for index in indexes:
                    pipeline.zadd(index, {record_key: self._score(impact)})
                    pipeline.zremrangebyrank(
                        index,
                        0,
                        -(REFORM_IMPACT_INDEX_LIMIT + 1),
                    )
                    pipeline.expire(index, ttl_seconds)
                replies = pipeline.execute()
        except Exception:  # noqa: BLE001  # a failed cache write returns False instead of failing the request
            record_cache_event(
                family=self.family,
                event="write-failed",
                started_at=time.perf_counter(),
                severity="WARNING",
            )
            return False
        # SET answers None when XX finds no record; any other write stands.
        return not only_if_present or replies[0] is not None

    def get_by_execution_id(self, execution_id: str) -> CachedReformImpact | None:
        """Return the job's impact, or None if absent, unreadable or unreachable."""
        try:
            value = self.client.get(self._record_key(execution_id))
        except Exception:  # noqa: BLE001  # a cache outage reads as absent, never a failed request
            return None
        return _impact_from_wire(
            decode_envelope(
                value,
                family=self.family,
                schema_version=REFORM_IMPACT_SCHEMA_VERSION,
            )
        )

    def seconds_left(self, impact: CachedReformImpact) -> int | None:
        """Return the whole seconds, rounded up, until lookups stop finding the impact.

        A lookup finds a record only through its scope index, so this is the
        earlier of the record's expiry and the index's, read from the cache's
        own expiry whatever lifetime each was written with; 0 once the index
        has expired. Return None when the impact has no worker handle, its
        record is missing or never expires, or the cache cannot be read.
        """
        if not impact.execution_id:
            return None
        try:
            record_milliseconds = self.client.pttl(
                self._record_key(impact.execution_id)
            )
            index_milliseconds = self.client.pttl(self._scope_index(impact))
        except (RedisError, OSError):
            return None
        if not isinstance(record_milliseconds, int) or record_milliseconds < 0:
            return None
        if (
            not isinstance(index_milliseconds, int)
            or index_milliseconds == PTTL_NO_EXPIRY
        ):
            return math.ceil(record_milliseconds / 1000)
        if index_milliseconds < 0:
            return 0
        return math.ceil(min(record_milliseconds, index_milliseconds) / 1000)

    def _read_index(
        self, index: str, limit: int
    ) -> list[tuple[str, str | bytes | None]]:
        """Return each record key in the index, newest first, with its stored value.

        Raise whatever the cache client raises when it cannot be read.
        """
        keys = self.client.zrevrange(index, 0, max(limit - 1, 0))  # type: ignore[attr-defined]
        return [(key, self.client.get(key)) for key in keys]

    def _decode_impact(self, value: str | bytes | None) -> CachedReformImpact | None:
        return _impact_from_wire(
            decode_envelope(
                value,
                family=self.family,
                schema_version=REFORM_IMPACT_SCHEMA_VERSION,
            )
        )

    @staticmethod
    @contextmanager
    def reads_fail_closed() -> Iterator[None]:
        """Make index lookups inside this block raise when the cache cannot be read.

        A lookup normally reads a cache it cannot reach, or a record it cannot
        read from it, as holding no impacts. Inside this block it raises
        CacheCoordinationError instead, so a caller for whom "nothing stored"
        must not hide an outage can select with the usual lookups. A record
        that is read but cannot be decoded is still skipped, as it is outside
        the block. Only the current context is affected.
        """
        token = _LOOKUPS_FAIL_CLOSED.set(True)
        try:
            yield
        finally:
            _LOOKUPS_FAIL_CLOSED.reset(token)

    def _from_index(self, index: str, limit: int) -> list[CachedReformImpact]:
        started_at = time.perf_counter()
        try:
            entries = self._read_index(index, limit)
        except Exception as error:
            # A cache outage reads as empty, never a failed request, unless
            # the caller asked lookups to fail closed.
            if not _LOOKUPS_FAIL_CLOSED.get():
                return []
            record_cache_event(
                family=self.family,
                event="coordination-failed",
                operation="index-read",
                started_at=started_at,
                severity="WARNING",
            )
            msg = "reform-impact lookups cannot read the cache"
            raise CacheCoordinationError(msg) from error
        impacts = [self._decode_impact(value) for _key, value in entries]
        return [impact for impact in impacts if impact is not None]

    def recent(self, limit: int) -> list[CachedReformImpact]:
        """Return up to ``limit`` impacts, most recently started first."""
        return self._from_index(self._recent_index(), limit)

    def matching(
        self,
        identity: ReformImpactIdentity,
        *,
        options_hash_pattern: str | None = None,
    ) -> list[CachedReformImpact]:
        """Return the cached impacts for one policy pair and scope, best match first.

        Exact ``options_hash`` matches sort before those matching
        ``options_hash_pattern``, a SQL ``LIKE`` pattern; ties go to the most
        recently started. Only the scope index's newest 1,000 entries are read.
        """
        scope = identity.scope
        options_hash = identity.options_hash
        probe = CachedReformImpact(
            reform_impact_id=0,
            baseline_policy_id=scope.baseline_policy_id,
            reform_policy_id=scope.reform_policy_id,
            country_id=scope.country_id,
            region=scope.region,
            dataset=scope.dataset,
            time_period=scope.time_period,
            options_json=None,
            options_hash=options_hash,
            api_version=identity.api_version,
            reform_impact_json={},
            status="",
            message=None,
            start_time=None,
            end_time=None,
            execution_id="",
        )
        impacts = self._from_index(
            self._scope_index(probe),
            REFORM_IMPACT_INDEX_LIMIT,
        )
        selected = [
            impact
            for impact in impacts
            if impact.options_hash == options_hash
            or (
                options_hash_pattern is not None
                and impact.options_hash is not None
                and _like_matches(impact.options_hash, options_hash_pattern)
            )
        ]
        return sorted(
            selected,
            key=lambda impact: (
                impact.options_hash == options_hash,
                impact.start_time or datetime.min,  # noqa: DTZ901  # start_time is a naive column, so the fallback must be naive to compare with it
                impact.reform_impact_id,
            ),
            reverse=True,
        )

    def update(
        self,
        execution_id: str,
        *,
        clear_execution_id: bool = False,
        record_ttl_seconds: int | None = None,
        **changes: Any,  # noqa: ANN401  # forwarded unchanged to dataclasses.replace
    ) -> CachedReformImpact | None:
        """Apply field changes to a cached impact and rewrite it under the same key.

        ``clear_execution_id`` drops the worker handle without moving the record,
        and ``record_ttl_seconds`` shortens its lifetime (see ``set``). The
        record is rewritten only if it still exists, so an update never puts
        back a record deleted after it was read. Return the updated impact, or
        None if it is missing or the write failed.
        """
        impact = self.get_by_execution_id(execution_id)
        if impact is None:
            return None
        if clear_execution_id:
            changes["execution_id"] = None
        updated = replace(impact, **changes)
        stored = self.set(
            updated,
            record_execution_id=execution_id,
            record_ttl_seconds=record_ttl_seconds,
            only_if_present=True,
        )
        return updated if stored else None

    def delete_failure(self, failure: CachedReformImpact) -> bool:
        """Remove a stored failure and its index entries, if its record still holds it.

        The record is found through the failure's scope index, so a typed
        failure whose worker handle was cleared is found as well. One script
        removes it only if the record still holds exactly the value read here,
        so a record rewritten since then, and every other job's record, is
        left alone. Return whether it was removed: False when its record has
        changed or is gone. Raise ValueError for an impact that is not a
        failure, and CacheCoordinationError when the cache cannot be read or
        written.
        """
        if failure.status != "error":
            msg = "only a failed reform impact can be deleted"
            raise ValueError(msg)
        started_at = time.perf_counter()
        scope_index = self._scope_index(failure)
        try:
            entries = self._read_index(scope_index, REFORM_IMPACT_INDEX_LIMIT)
            stored = next(
                (
                    (record_key, value)
                    for record_key, value in entries
                    if value is not None and self._decode_impact(value) == failure
                ),
                None,
            )
            deleted = stored is not None and bool(
                self.client.eval(
                    DELETE_UNCHANGED_RECORD,
                    3,
                    stored[0],
                    scope_index,
                    self._recent_index(),
                    stored[1],
                )
            )
        except Exception as error:
            record_cache_event(
                family=self.family,
                event="coordination-failed",
                operation="failure-delete",
                started_at=started_at,
                severity="WARNING",
            )
            msg = "the stored reform-impact failure could not be deleted"
            raise CacheCoordinationError(msg) from error
        record_cache_event(
            family=self.family,
            event="deleted" if deleted else "delete-skipped",
            operation="failure-delete",
            started_at=started_at,
        )
        return deleted

    def delete_matching_computing(
        self,
        scope: ReformImpactScope,
        *,
        options_hash: str,
    ) -> None:
        """Remove in-flight (``computing``) impacts for this scope and options.

        Cache failures are ignored, so a stale entry may survive until it expires.
        """
        # Deletion historically omits api_version, so search the bounded recent
        # index and remove only matching in-flight values.
        impacts = self.recent(REFORM_IMPACT_INDEX_LIMIT)
        selected = [
            impact
            for impact in impacts
            if impact.country_id == scope.country_id
            and impact.reform_policy_id == scope.reform_policy_id
            and impact.baseline_policy_id == scope.baseline_policy_id
            and impact.region == scope.region
            and impact.dataset == scope.dataset
            and impact.time_period == scope.time_period
            and impact.options_hash == options_hash
            and impact.status == "computing"
        ]
        if not selected:
            return
        try:
            with self.client.pipeline(transaction=True) as pipeline:
                for impact in selected:
                    key = self._record_key(impact.execution_id)
                    pipeline.delete(key)
                    pipeline.zrem(self._scope_index(impact), key)
                    pipeline.zrem(self._recent_index(), key)
                pipeline.execute()
        except Exception:  # noqa: BLE001  # best-effort cleanup of stale computing records
            return


def reform_impact_id(execution_id: str) -> int:
    """Stable positive cache-local identifier for the historical response field."""
    digest = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:15]
    return int(digest, 16)
