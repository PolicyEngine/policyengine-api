from policyengine_api.data.data import database
import streamlit as st

st.title("PolicyEngine API dashboard")

# Add a text box that the user can enter a SQL query into, with a submit button and a table showing the results.

query = st.text_area("Enter a SQL query", "SELECT * FROM policies LIMIT 10;")
if st.button("Submit"):
    try:
        results = database.query(query)
        st.table(results.fetchall())
    except Exception as e:
        st.error(e)

st.subheader("Logs")

# Show the logs from Google Cloud Logging.

from google.cloud import logging
from google.cloud.logging_v2.types import ListLogEntriesRequest

logging_client = logging.Client()
logger = logging_client.logger("policyengine-api")

# Filter to find logs of type JSON with an 'api' field.

filter_ = 'jsonPayload.api="compute"'
iterator = logger.list_entries(filter_=filter_)
entries = list(iterator)
