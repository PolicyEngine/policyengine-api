from policyengine_api.services.metadata_service import MetadataService

metadata_service = MetadataService()


def test_units():
    m = metadata_service.get_metadata("us")
    assert (
        m["parameters"]["gov.states.md.tax.income.rates.head[0].rate"]["unit"]
        == "/1"
    )
    assert (
        m["parameters"]["gov.states.md.tax.income.rates.head[0].threshold"][
            "unit"
        ]
        == "currency-USD"
    )
    assert (
        m["parameters"]["gov.irs.credits.eitc.phase_out.start[0].amount"][
            "unit"
        ]
        == "currency-USD"
    )
