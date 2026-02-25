"""Tests for SQLAlchemy v2 compatibility.

These tests verify that the database layer works correctly with
SQLAlchemy v2, specifically:
- The _ResultProxy wrapper provides fetchone()/fetchall() on eagerly
  fetched results.
- The remote (non-local) query path uses connection-based execution
  instead of the removed engine.execute().
- Row objects returned from the remote path support dict-like access
  (dict(row) and row["key"]).
"""

import pytest
import sqlalchemy

from policyengine_api.data.data import _ResultProxy, PolicyEngineDatabase


class TestSQLAlchemyVersion:
    """Verify that SQLAlchemy v2 is installed."""

    def test_sqlalchemy_version_is_v2(self):
        major = int(sqlalchemy.__version__.split(".")[0])
        assert (
            major >= 2
        ), f"Expected SQLAlchemy v2+, got {sqlalchemy.__version__}"


class TestResultProxy:
    """Test the _ResultProxy wrapper that bridges SQLAlchemy v2
    connection-scoped results with the existing query() API."""

    def test_fetchone_returns_dict_like_rows(self):
        """Rows returned by fetchone() should support dict() and
        key-based access."""
        engine = sqlalchemy.create_engine("sqlite://")
        with engine.connect() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)"
            )
            conn.exec_driver_sql("INSERT INTO test VALUES (1, 'hello')")
            result = conn.exec_driver_sql("SELECT * FROM test")
            proxy = _ResultProxy(result)

        row = proxy.fetchone()
        assert row is not None
        assert dict(row) == {"id": 1, "name": "hello"}
        assert row["id"] == 1
        assert row["name"] == "hello"

    def test_fetchone_returns_none_when_exhausted(self):
        engine = sqlalchemy.create_engine("sqlite://")
        with engine.connect() as conn:
            conn.exec_driver_sql("CREATE TABLE test (id INTEGER PRIMARY KEY)")
            result = conn.exec_driver_sql("SELECT * FROM test")
            proxy = _ResultProxy(result)

        assert proxy.fetchone() is None

    def test_fetchall_returns_all_rows(self):
        engine = sqlalchemy.create_engine("sqlite://")
        with engine.connect() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)"
            )
            conn.exec_driver_sql("INSERT INTO test VALUES (1, 'a')")
            conn.exec_driver_sql("INSERT INTO test VALUES (2, 'b')")
            conn.exec_driver_sql("INSERT INTO test VALUES (3, 'c')")
            result = conn.exec_driver_sql("SELECT * FROM test")
            proxy = _ResultProxy(result)

        rows = proxy.fetchall()
        assert len(rows) == 3
        assert dict(rows[0]) == {"id": 1, "val": "a"}
        assert dict(rows[2]) == {"id": 3, "val": "c"}

    def test_fetchone_then_fetchall_respects_cursor_position(self):
        engine = sqlalchemy.create_engine("sqlite://")
        with engine.connect() as conn:
            conn.exec_driver_sql("CREATE TABLE test (id INTEGER PRIMARY KEY)")
            conn.exec_driver_sql("INSERT INTO test VALUES (1)")
            conn.exec_driver_sql("INSERT INTO test VALUES (2)")
            conn.exec_driver_sql("INSERT INTO test VALUES (3)")
            result = conn.exec_driver_sql("SELECT * FROM test")
            proxy = _ResultProxy(result)

        first = proxy.fetchone()
        assert dict(first) == {"id": 1}
        remaining = proxy.fetchall()
        assert len(remaining) == 2
        assert dict(remaining[0]) == {"id": 2}

    def test_result_proxy_for_insert_statement(self):
        """INSERT statements produce no rows; _ResultProxy should
        handle this gracefully."""
        engine = sqlalchemy.create_engine("sqlite://")
        with engine.connect() as conn:
            conn.exec_driver_sql("CREATE TABLE test (id INTEGER PRIMARY KEY)")
            result = conn.exec_driver_sql("INSERT INTO test VALUES (1)")
            proxy = _ResultProxy(result)

        assert proxy.fetchone() is None
        assert proxy.fetchall() == []


class TestRemoteQueryPath:
    """Test the non-local query path that uses SQLAlchemy engine
    with connection-based execution (v2 pattern)."""

    def _make_remote_db(self):
        """Create a PolicyEngineDatabase-like object that uses
        a SQLAlchemy engine (the 'remote' path) but backed by
        in-memory SQLite for testing."""
        db = PolicyEngineDatabase.__new__(PolicyEngineDatabase)
        db.local = False
        db.pool = sqlalchemy.create_engine("sqlite://")
        # Initialize schema using the remote path
        with db.pool.connect() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE test_table "
                "(id INTEGER PRIMARY KEY, name TEXT, value REAL)"
            )
            conn.commit()
        return db

    def test_remote_insert_and_select(self):
        """Test INSERT then SELECT through the remote query path."""
        db = self._make_remote_db()

        # Note: remote path converts ? to %s for MySQL, but SQLite
        # uses ? natively. Since exec_driver_sql passes to the DBAPI
        # driver directly and SQLite's driver uses ?, we need to
        # test with the actual query() method which does the conversion.
        # For SQLite DBAPI, ? is the native marker.

        # Use exec_driver_sql directly to bypass ?->%s conversion
        # (which would break SQLite)
        db._execute_remote(
            [
                "INSERT INTO test_table (id, name, value) VALUES (?, ?, ?)",
                (1, "test", 3.14),
            ]
        )

        result = db._execute_remote(
            ["SELECT * FROM test_table WHERE id = ?", (1,)]
        )
        row = result.fetchone()
        assert row is not None
        assert row["id"] == 1
        assert row["name"] == "test"
        assert row["value"] == 3.14
        assert dict(row) == {"id": 1, "name": "test", "value": 3.14}

    def test_remote_select_no_results(self):
        db = self._make_remote_db()
        result = db._execute_remote(
            ["SELECT * FROM test_table WHERE id = ?", (999,)]
        )
        assert result.fetchone() is None

    def test_remote_update(self):
        db = self._make_remote_db()
        db._execute_remote(
            [
                "INSERT INTO test_table (id, name, value) VALUES (?, ?, ?)",
                (1, "original", 1.0),
            ]
        )
        db._execute_remote(
            [
                "UPDATE test_table SET name = ? WHERE id = ?",
                ("updated", 1),
            ]
        )
        result = db._execute_remote(
            ["SELECT * FROM test_table WHERE id = ?", (1,)]
        )
        row = result.fetchone()
        assert row["name"] == "updated"

    def test_remote_delete(self):
        db = self._make_remote_db()
        db._execute_remote(
            [
                "INSERT INTO test_table (id, name, value) VALUES (?, ?, ?)",
                (1, "to_delete", 0.0),
            ]
        )
        db._execute_remote(["DELETE FROM test_table WHERE id = ?", (1,)])
        result = db._execute_remote(
            ["SELECT * FROM test_table WHERE id = ?", (1,)]
        )
        assert result.fetchone() is None
