"""Safety checks shared by destructive Stage 7 qualification tooling."""

from sqlalchemy.engine import make_url


def assert_safe_toy_database_url(database_url: str) -> None:
    """Reject destructive toy-test operations against non-local databases."""

    url = make_url(database_url)
    is_local_mysql = url.get_backend_name() == "mysql" and url.host in {
        "127.0.0.1",
        "localhost",
    }
    is_toy_database = bool(url.database and url.database.endswith("_toy"))
    if not is_local_mysql or not is_toy_database:
        raise ValueError(
            "Stage 7 integration tests require a local MySQL database ending in '_toy'"
        )
