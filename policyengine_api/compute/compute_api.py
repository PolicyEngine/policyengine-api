"""
The Compute API is a separate Flask app that runs on a separate port. 
It is designed to be run on a separate server from the main PolicyEngine web app, so that it can
be used for compute-intensive tasks without affecting the main server.
"""

import flask
from flask_cors import CORS
from policyengine_api.constants import GET, POST, __version__
from policyengine_api.country import PolicyEngineCountry

app = flask.Flask(__name__)

CORS(app)

uk = PolicyEngineCountry("policyengine_uk", "uk")
us = PolicyEngineCountry("policyengine_us", "us")
countries = dict(uk=uk, us=us)


@app.route("/", methods=[GET])
def home():
    return f"<h1>PolicyEngine compute API v{__version__}</h1><p>Use this API to compute the impact of public policy on economies.</p>"
