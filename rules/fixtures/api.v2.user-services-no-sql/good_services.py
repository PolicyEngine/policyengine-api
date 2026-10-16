"""Proof fixture: a user service that leaves queries to its connector. The rule must accept it."""

from policyengine_api.services.v2.user_policies.database_connectors import reads


def list_user_policies(session, user_id: str):
    return reads.list_user_policies(session, user_id=user_id)
