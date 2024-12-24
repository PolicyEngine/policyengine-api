from flask import Flask, g
from werkzeug.local import LocalProxy
from authlib.integrations.flask_oauth2 import ResourceProtector


def configure(app: Flask, require_auth: ResourceProtector):
    """
    Configure the application to attempt to get and validate a bearer token.
    If there is a token and it's valid the user id is added to the request context
    which can be accessed via get_user_id
    Otherwise, the request is accepted but get_user_id returns None

    This supports our current auth model where only user-specific actions are restricted and
    then only to allow the user
    """

    # If the user is authenticated then get the user id from the token
    # And add it to the flask request context.
    @app.before_request
    def get_user():
        if "user_id" in g:
            return None
        try:
            with require_auth.acquire_token() as token:
                g.user_id = token.user_id
        except Exception as ex:
            print(f"Unable to parse a valid bearer token from request: {ex}")
            g.user_id = None


def get_user_id() -> None | str:
    if "user_id" not in g:
        print(
            "There is no user_id in the FLASK context. Please use 'configure' on your app to enable"
        )
        return None
    return g.user_id
