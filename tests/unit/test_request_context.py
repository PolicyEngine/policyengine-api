from unittest.mock import Mock, patch

from flask import Flask, g

from policyengine_api.request_context import (
    adopt_observability_id,
    current_observability_id,
    restore_observability_id,
    start_observability_id,
)


FIRST_ID = "00000000-0000-4000-8000-000000000001"
SECOND_ID = "00000000-0000-4000-8000-000000000002"


def test_start_uses_valid_incoming_identifier_and_binds_runtime():
    app = Flask(__name__)
    runtime = Mock()

    with (
        app.test_request_context(),
        patch("policyengine_api.observability.get_runtime", return_value=runtime),
    ):
        g.incoming_observability_id = FIRST_ID
        g.observability_id = None

        result = start_observability_id()

        assert result == FIRST_ID
        assert current_observability_id() == FIRST_ID
        runtime.set_context.assert_called_once_with(observability_id=FIRST_ID)


def test_downstream_adoption_cannot_replace_bound_identifier():
    app = Flask(__name__)

    with app.test_request_context():
        g.observability_id = FIRST_ID

        result = adopt_observability_id(SECOND_ID)

        assert result == FIRST_ID
        assert current_observability_id() == FIRST_ID


def test_durable_state_restoration_replaces_request_candidate():
    app = Flask(__name__)
    runtime = Mock()

    with (
        app.test_request_context(),
        patch("policyengine_api.observability.get_runtime", return_value=runtime),
    ):
        g.observability_id = FIRST_ID

        result = restore_observability_id(SECOND_ID)

        assert result == SECOND_ID
        assert current_observability_id() == SECOND_ID
        runtime.set_context.assert_called_once_with(observability_id=SECOND_ID)


def test_runtime_failure_does_not_change_identifier_selection():
    app = Flask(__name__)
    runtime = Mock()
    runtime.set_context.side_effect = RuntimeError("observability unavailable")

    with (
        app.test_request_context(),
        patch("policyengine_api.observability.get_runtime", return_value=runtime),
    ):
        g.incoming_observability_id = FIRST_ID
        g.observability_id = None

        assert start_observability_id() == FIRST_ID
        assert current_observability_id() == FIRST_ID
