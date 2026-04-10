from contextlib import contextmanager
import hashlib
from threading import Lock
from policyengine_api.data import database
import datetime


LOCAL_REFORM_IMPACT_LOCK = Lock()
REFORM_IMPACT_SCHEMA_LOCK = Lock()
REFORM_IMPACT_LOCK_TIMEOUT_SECONDS = 5


class ReformImpactsService:
    """
    Service for storing and retrieving economy-wide reform impacts;
    this is connected to the shared reform_impact table.
    """

    def __init__(self):
        self._schema_checked = False

    def _ensure_remote_schema(self) -> None:
        if database.local or self._schema_checked:
            return

        with REFORM_IMPACT_SCHEMA_LOCK:
            if self._schema_checked:
                return

            existing_columns = {
                row["Field"]
                for row in database.query("SHOW COLUMNS FROM reform_impact").fetchall()
            }
            required_columns = {
                "dataset": (
                    "ALTER TABLE reform_impact "
                    "ADD COLUMN dataset VARCHAR(255) NOT NULL DEFAULT 'default'"
                ),
                "execution_id": (
                    "ALTER TABLE reform_impact "
                    "ADD COLUMN execution_id VARCHAR(255) NULL"
                ),
                "end_time": (
                    "ALTER TABLE reform_impact ADD COLUMN end_time DATETIME NULL"
                ),
            }

            for column_name, alter_query in required_columns.items():
                if column_name in existing_columns:
                    continue
                try:
                    database.query(alter_query)
                except Exception as error:
                    if "Duplicate column name" not in str(error):
                        raise

            self._schema_checked = True

    def _build_lock_name(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        api_version,
    ) -> str:
        raw_key = (
            f"{country_id}:{policy_id}:{baseline_policy_id}:{region}:{dataset}:"
            f"{time_period}:{options_hash}:{api_version}"
        )
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return f"ri:{digest[:61]}"

    @contextmanager
    def claim_lock(
        self,
        *,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        api_version,
        timeout_seconds: int = REFORM_IMPACT_LOCK_TIMEOUT_SECONDS,
    ):
        if database.local:
            with LOCAL_REFORM_IMPACT_LOCK:
                yield
            return

        lock_name = self._build_lock_name(
            country_id=country_id,
            policy_id=policy_id,
            baseline_policy_id=baseline_policy_id,
            region=region,
            dataset=dataset,
            time_period=time_period,
            options_hash=options_hash,
            api_version=api_version,
        )
        with database.pool.connect() as conn:
            acquired = (
                conn.exec_driver_sql(
                    "SELECT GET_LOCK(%s, %s) AS acquired",
                    (lock_name, timeout_seconds),
                )
                .mappings()
                .first()
            )
            if acquired is None or acquired["acquired"] != 1:
                raise TimeoutError(
                    f"Could not acquire reform impact lock for {country_id}/{policy_id}/{time_period}"
                )

            try:
                yield
            finally:
                conn.exec_driver_sql(
                    "SELECT RELEASE_LOCK(%s) AS released", (lock_name,)
                )
                conn.commit()

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
        try:
            self._ensure_remote_schema()
            query = (
                "SELECT reform_impact_json, status, message, start_time, execution_id FROM "
                "reform_impact WHERE country_id = ? AND reform_policy_id = ? AND "
                "baseline_policy_id = ? AND region = ? AND time_period = ? AND "
                "options_hash = ? AND api_version = ? AND dataset = ? "
                "ORDER BY start_time DESC, reform_impact_id DESC"
            )
            return database.query(
                query,
                (
                    country_id,
                    policy_id,
                    baseline_policy_id,
                    region,
                    time_period,
                    options_hash,
                    api_version,
                    dataset,
                ),
            ).fetchall()
        except Exception as e:
            print(f"Error getting all reform impacts: {str(e)}")
            raise e

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
        try:
            self._ensure_remote_schema()
            query = (
                "INSERT INTO reform_impact (country_id, reform_policy_id, baseline_policy_id, "
                "region, dataset, time_period, options_json, options_hash, status, api_version, "
                "reform_impact_json, start_time, execution_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            database.query(
                query,
                (
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
                ),
            )
        except Exception as e:
            print(f"Error setting reform impact: {str(e)}")
            raise e

    def update_reform_impact_execution_id(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        current_execution_id,
        new_execution_id,
    ):
        try:
            self._ensure_remote_schema()
            query = (
                "UPDATE reform_impact SET execution_id = ? WHERE country_id = ? AND "
                "reform_policy_id = ? AND baseline_policy_id = ? AND region = ? AND "
                "time_period = ? AND options_hash = ? AND dataset = ? AND "
                "execution_id = ? AND status = 'computing'"
            )
            result = database.query(
                query,
                (
                    new_execution_id,
                    country_id,
                    policy_id,
                    baseline_policy_id,
                    region,
                    time_period,
                    options_hash,
                    dataset,
                    current_execution_id,
                ),
            )
            return getattr(result, "rowcount", None)
        except Exception as e:
            print(f"Error updating reform impact execution id: {str(e)}")
            raise e

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
        try:
            self._ensure_remote_schema()
            query = (
                "DELETE FROM reform_impact WHERE country_id = ? AND "
                "reform_policy_id = ? AND baseline_policy_id = ? AND "
                "region = ? AND time_period = ? AND options_hash = ? AND "
                "dataset = ? AND status = 'computing'"
            )

            database.query(
                query,
                (
                    country_id,
                    policy_id,
                    baseline_policy_id,
                    region,
                    time_period,
                    options_hash,
                    dataset,
                ),
            )
        except Exception as e:
            print(f"Error deleting reform impact: {str(e)}")
            raise e

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
        try:
            self._ensure_remote_schema()
            query = (
                "UPDATE reform_impact SET status = ?, message = ?, end_time = ? WHERE "
                "country_id = ? AND reform_policy_id = ? AND baseline_policy_id = ? AND "
                "region = ? AND time_period = ? AND options_hash = ? AND dataset = ? AND "
                "execution_id = ?"
            )
            database.query(
                query,
                (
                    "error",
                    message,
                    datetime.datetime.strftime(
                        datetime.datetime.now(datetime.timezone.utc),
                        "%Y-%m-%d %H:%M:%S.%f",
                    ),
                    country_id,
                    policy_id,
                    baseline_policy_id,
                    region,
                    time_period,
                    options_hash,
                    dataset,
                    execution_id,
                ),
            )
        except Exception as e:
            print(
                f"Error setting error reform impact (something must be REALLY wrong): {str(e)}"
            )
            raise e

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
        try:
            self._ensure_remote_schema()
            query = (
                "UPDATE reform_impact SET status = ?, message = ?, end_time = ?, "
                "reform_impact_json = ? WHERE country_id = ? AND reform_policy_id = ? AND "
                "baseline_policy_id = ? AND region = ? AND time_period = ? AND "
                "options_hash = ? AND dataset = ? AND execution_id = ?"
            )
            database.query(
                query,
                (
                    "ok",
                    "Completed",
                    datetime.datetime.strftime(
                        datetime.datetime.now(datetime.timezone.utc),
                        "%Y-%m-%d %H:%M:%S.%f",
                    ),
                    reform_impact_json,
                    country_id,
                    reform_policy_id,
                    baseline_policy_id,
                    region,
                    time_period,
                    options_hash,
                    dataset,
                    execution_id,
                ),
            )
        except Exception as e:
            print(f"Error setting completed reform impact: {str(e)}")
            raise e
