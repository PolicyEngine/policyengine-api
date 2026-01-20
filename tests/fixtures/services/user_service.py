import pytest

valid_user_record = {
    "user_id": 1,
    "auth0_id": "123",
    "username": "person1",
    "primary_country": "US",
    "user_since": 1678658906,
}


@pytest.fixture
def existing_user_profile(test_db):
    """Insert an existing user record into the database."""
    test_db.query(
        "INSERT INTO user_profiles (user_id, auth0_id, username, primary_country, user_since) VALUES (?, ?, ?, ?, ?)",
        (
            valid_user_record["user_id"],
            valid_user_record["auth0_id"],
            valid_user_record["username"],
            valid_user_record["primary_country"],
            valid_user_record["user_since"],
        ),
    )
    inserted_row = test_db.query(
        "SELECT * FROM user_profiles WHERE auth0_id = ?",
        (valid_user_record["auth0_id"],),
    ).fetchone()

    return inserted_row
