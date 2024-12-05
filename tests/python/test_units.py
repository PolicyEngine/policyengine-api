from policyengine_api.routes.metadata_routes import get_metadata


def test_units():
    m = get_metadata("us")
    assert (
        m["result"]["parameters"][
            "gov.states.md.tax.income.rates.head[0].rate"
        ]["unit"]
        == "/1"
    )
    assert (
        m["result"]["parameters"][
            "gov.states.md.tax.income.rates.head[0].threshold"
        ]["unit"]
        == "currency-USD"
    )
    assert (
        m["result"]["parameters"][
            "gov.irs.credits.eitc.phase_out.start[0].amount"
        ]["unit"]
        == "currency-USD"
    )
