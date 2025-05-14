from google.cloud.logging import Client

logger = Client().logger("policyengine-api")
