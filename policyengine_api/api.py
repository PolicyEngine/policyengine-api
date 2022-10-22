import flask
from policyengine_api.constants import GET, POST, __version__

app = flask.Flask(__name__)


@app.route("/", methods=[GET])
def home():
    return f"<h1>PolicyEngine households API v{__version__}</h1><p>Use this API to compute the impact of public policy on individual households.</p>"
