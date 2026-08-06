from policyengine_api.constants import REPO
from policyengine_api.data.orm import SessionManager


def create_sqlite_v1_schema(manager: SessionManager) -> None:
    """Install the explicit local schema without compiling MySQL metadata."""

    schema = (REPO / "policyengine_api/data/initialise_local.sql").read_text(
        encoding="utf-8"
    )
    with manager.engine.connect() as connection:
        connection.connection.driver_connection.executescript(schema)
