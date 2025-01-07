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
        try:
            token = require_auth.acquire_token()
            print(f"Validated JWT for sub {g.authlib_server_oauth2_token.sub}")
        except Exception as ex:
            print(f"Unable to parse a valid bearer token from request: {ex}")


def get_user() -> None | str:
    # I didn't see this documented anywhere, but if you look at the source code
    # the validator stores the token in the flask global context under this name.
    if "authlib_server_oauth2_token" not in g:
        print(
            "authlib_server_oauth2_token is not in the flask global context. Please make sure you called 'configure' on the app"
        )
        return None
    if "sub" not in g.authlib_server_oauth2_token:
        print(
            "ERROR: authlib_server_oauth2_token does not contain a sub field. The JWT validator should force this to be true."
        )
        return None
    return g.authlib_server_oauth2_token.sub
