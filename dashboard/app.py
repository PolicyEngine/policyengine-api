import streamlit as st
from sqlalchemy import select

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Policy


st.title("PolicyEngine API dashboard")


def serialize_policy(policy: Policy) -> dict:
    return {
        column.name: getattr(policy, column.name) for column in Policy.__table__.columns
    }


st.subheader("Recent policies")
if st.button("Refresh policies"):
    sessions = get_v1_session_factory()
    with sessions() as session:
        policies = session.scalars(select(Policy).limit(10)).all()
        st.table([serialize_policy(policy) for policy in policies])


st.subheader("Look up a policy")
policy_id = int(st.text_input("Enter a policy ID", "1", key="policy_lookup_text"))
country_id = st.text_input("Enter a country ID", "uk", key="policy_lookup_country")
if st.button("Look up policy", key="policy_lookup"):
    sessions = get_v1_session_factory()
    with sessions() as session:
        policy = session.scalar(
            select(Policy).where(
                Policy.id == policy_id,
                Policy.country_id == country_id,
            )
        )
        if policy is None:
            st.error("Policy not found")
        else:
            st.table([serialize_policy(policy)])


st.subheader("Set a policy's label")
policy_id = int(st.text_input("Enter a policy ID", "1"))
country_id = st.text_input("Enter a country ID", "uk")
new_label = st.text_input("Enter a new label", "New label", key="policy_label_text")
if st.button("Set policy label", key="policy_label"):
    sessions = get_v1_session_factory()
    with sessions.begin() as session:
        policy = session.scalar(
            select(Policy).where(
                Policy.id == policy_id,
                Policy.country_id == country_id,
            )
        )
        if policy is None:
            st.error("Policy not found")
        else:
            policy.label = new_label
            st.success("Success!")


st.subheader("Delete a policy")
policy_id = int(st.text_input("Enter a policy ID", "1", key="policy_delete_text"))
country_id = st.text_input("Enter a country ID", "uk", key="policy_delete_country")
if st.button("Delete policy", key="policy_delete"):
    sessions = get_v1_session_factory()
    with sessions.begin() as session:
        policy = session.scalar(
            select(Policy).where(
                Policy.id == policy_id,
                Policy.country_id == country_id,
            )
        )
        if policy is None:
            st.error("Policy not found")
        else:
            session.delete(policy)
            st.success("Success!")
