from unittest.mock import MagicMock, patch

from policyengine_api.endpoints.simulation import get_simulations


def test_get_simulations_reads_from_remote_database():
    mock_database = MagicMock()
    mock_database.query.return_value.fetchall.return_value = [{"id": 1}]

    with patch(
        "policyengine_api.endpoints.simulation.get_remote_database",
        return_value=mock_database,
    ):
        result = get_simulations()

    mock_database.query.assert_called_once_with(
        "SELECT * FROM reform_impact ORDER BY start_time DESC LIMIT 100",
    )
    assert result == {"result": [{"id": 1}]}
