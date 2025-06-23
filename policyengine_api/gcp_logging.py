import os

if os.getenv("ENV") == "local":
    import logging

    logger = logging.getLogger("local-logger")
    logger.warning("Using local logger (GCP logging disabled)")
else:
    from google.cloud.logging import Client

    logger = Client().logger("policyengine-api")
