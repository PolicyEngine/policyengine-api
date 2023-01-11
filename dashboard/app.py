from policyengine_api.data.data import database
import streamlit as st

st.title("PolicyEngine API dashboard")

# Add a text box that the user can enter a SQL query into, with a submit button and a table showing the results.

st.subheader("Run a SQL query")

query = st.text_area("Enter a SQL query", "SELECT * FROM policy LIMIT 10;")
if st.button("Submit"):
    try:
        results = database.query(query)
        st.table(results.fetchall())
    except Exception as e:
        st.error(e)

# Enable the user to look up a policy by ID.

st.subheader("Look up a policy")

policy_id = int(
    st.text_input("Enter a policy ID", "1", key="policy_lookup_text")
)
country_id = st.text_input(
    "Enter a country ID", "uk", key="policy_lookup_country"
)
if st.button("Look up policy", key="policy_lookup"):
    try:
        results = database.query(
            f"SELECT * FROM policy WHERE id = '{policy_id}' AND country_id = '{country_id}' LIMIT 10;"
        )
        st.table(results.fetchall())
    except Exception as e:
        st.error(e)

# Enable the user to set the label of a policy.

st.subheader("Set a policy's label")

policy_id = int(st.text_input("Enter a policy ID", "1"))
country_id = st.text_input("Enter a country ID", "uk")
new_label = st.text_input(
    "Enter a new label", "New label", key="policy_label_text"
)
if st.button("Set policy label", key="policy_label"):
    try:
        database.set_policy_label(policy_id, country_id, new_label)
        st.success("Success!")
    except Exception as e:
        st.error(e)

# Enable the user to delete a policy.

st.subheader("Delete a policy")

policy_id = int(
    st.text_input("Enter a policy ID", "1", key="policy_delete_text")
)
country_id = st.text_input(
    "Enter a country ID", "uk", key="policy_delete_country"
)
if st.button("Delete policy", key="policy_delete"):
    try:
        database.delete_policy(policy_id, country_id)
        st.success("Success!")
    except Exception as e:
        st.error(e)
