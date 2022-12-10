from google.cloud.logging import Client
import sqlalchemy
import os


logging_client = Client()
logging_client.setup_logging()
logger = logging_client.logger("policyengine-api")