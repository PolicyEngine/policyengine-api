import json
from typing import Any
from policyengine_api.data import database


class UserService:
    def create_profile(
        self,
        primary_country: str,
        auth0_id: str,
        username: str | None,
        user_since: str,
    ) -> tuple[bool, Any]:
        """
        returns true if a new record was created and false otherwise.
        """
        # TODO: this is not written as an atomic operation. This will cause intermittent errors
        # in some cases
        # https://github.com/PolicyEngine/policyengine-api/issues/2058 to resolve after
        # this refactor.
        row = self.get_profile(auth0_id=auth0_id)
        if row is not None:
            return False, row
        # Unfortunately, it's not possible to use RETURNING
        # with SQLite3 without rewriting the PolicyEngineDatabase
        # object or implementing a true ORM, thus the double query
        database.query(
            f"INSERT INTO user_profiles (primary_country, auth0_id, username, user_since) VALUES (?, ?, ?, ?)",
            (primary_country, auth0_id, username, user_since),
        )

        row = self.get_profile(auth0_id=auth0_id)

        return (True, row)

    def get_profile(
        self, auth0_id: str | None = None, user_id: str | None = None
    ) -> Any | None:
        key = "user_id" if auth0_id is None else "auth0_id"
        value = user_id if auth0_id is None else auth0_id
        if value is None:
            raise ValueError("you must specify either auth0_id or user_id")
        row = database.query(
            f"SELECT * FROM user_profiles WHERE {key} = ?",
            (value,),
        ).fetchone()

        return row

    def update_profile(
        self,
        user_id: str,
        primary_country: str | None,
        username: str | None,
        user_since: str,
    ) -> bool:
        fields = dict(
            primary_country=primary_country,
            username=username,
            user_since=user_since,
        )
        if self.get_profile(user_id=user_id) is None:
            return False

        with_values = [key for key in fields if fields[key] is not None]
        fields_update = ",".join([f"{key} = ?" for key in with_values])
        query = f"UPDATE user_profiles SET {fields_update} WHERE user_id = ?"
        values = [fields[key] for key in with_values] + [user_id]

        print(f"Updating record {user_id}")
        try:
            database.query(query, (tuple(values)))
        except Exception as ex:
            print(f"ERROR: unable to update user record: {ex}")
            raise
        return True
