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