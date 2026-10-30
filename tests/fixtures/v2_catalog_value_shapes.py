"""A small catalog with one example of each value shape extraction accepts.

The complete installed catalog (about 1.2 million parameter values) is
published in CI only when a change can affect it
(.github/scripts/decide_full_catalog_tests.sh). Every pull request publishes
this catalog to PostgreSQL instead and checks that each shape comes back
unchanged (tests/integration/test_v2_catalog_publication.py): every JSON value
type a parameter value may hold, date-only and naive start dates, year-1,
one-day and open-ended date ranges, bracket parameters and their nodes, and
the text, number and membership-list region filters.

It is the deterministic fixture catalog from tests/fixtures/v2_catalog.py with
these cases added, so that catalog's counts stay as its own tests assert.
"""

from __future__ import annotations

import math
from dataclasses import KW_ONLY, dataclass
from datetime import date, datetime
from enum import Enum
from types import SimpleNamespace
from typing import TYPE_CHECKING

import numpy as np

from policyengine_api.data.v2.catalog.extraction import extract_catalog
from tests.fixtures.v2_catalog import (
    POLICYENGINE_VERSION,
    bundle,
    installed_version,
    source_models,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.records import NormalizedCatalog
    from policyengine_api.json_types import JSONValue


class _FilingStatus(Enum):
    SINGLE = "SINGLE"
    JOINT = "JOINT"


@dataclass(frozen=True)
class ValueCase:
    """One source parameter value and the JSON value the catalog stores for it.

    ``start`` and ``end`` are as the source gives them; the catalog stores
    them as UTC datetimes.
    """

    start: date | datetime
    end: date | datetime | None
    _: KW_ONLY
    value: object
    stored_value: JSONValue


@dataclass(frozen=True)
class ParameterCase:
    """A US parameter whose values, oldest first, each test one shape."""

    name: str
    data_type: type | None
    values: tuple[ValueCase, ...]

    def source(self) -> SimpleNamespace:
        """Return the parameter as the public model lists it."""
        return SimpleNamespace(
            name=self.name,
            label=f"Value shape {self.name.rsplit('.', maxsplit=1)[-1]}",
            description=None,
            data_type=self.data_type,
            unit=None,
            parameter_values=[
                SimpleNamespace(
                    value=value.value, start_date=value.start, end_date=value.end
                )
                for value in self.values
            ],
        )


# .py reads Core's earliest instant, 0000-01-01, as year 1, and gives naive
# datetimes; extraction reads both, and dates, as UTC.
EARLIEST = datetime(1, 1, 1)
TEXT_WITH_COPY_ESCAPES = 'Tab\there, new\nline, back\\slash, "quotes", café €'
BRACKET_PARAMETER_NODES = (
    "gov.value_shapes.scale[0]",
    "gov.value_shapes.scale[1]",
)
PARAMETER_CASES = (
    ParameterCase(
        name="gov.value_shapes.flag",
        data_type=bool,
        values=(
            ValueCase(EARLIEST, datetime(2024, 12, 31), value=True, stored_value=True),
            ValueCase(datetime(2025, 1, 1), None, value=False, stored_value=False),
        ),
    ),
    ParameterCase(
        name="gov.value_shapes.count",
        data_type=int,
        values=(
            ValueCase(
                datetime(2025, 1, 1), datetime(2025, 6, 30), value=0, stored_value=0
            ),
            # In force for one day only.
            ValueCase(
                datetime(2025, 7, 1), datetime(2025, 7, 1), value=-3, stored_value=-3
            ),
            ValueCase(datetime(2025, 7, 2), None, value=12, stored_value=12),
        ),
    ),
    ParameterCase(
        name="gov.value_shapes.amount",
        data_type=float,
        values=(
            ValueCase(
                date(2024, 1, 1),
                date(2024, 12, 31),
                value=0.30000000000000004,
                stored_value=0.30000000000000004,
            ),
            # A whole number that must stay a float.
            ValueCase(date(2025, 1, 1), None, value=12000.0, stored_value=12000.0),
        ),
    ),
    ParameterCase(
        name="gov.value_shapes.cap",
        data_type=float,
        values=(
            ValueCase(
                datetime(2024, 1, 1),
                datetime(2024, 12, 31),
                value=math.inf,
                stored_value="Infinity",
            ),
            ValueCase(
                datetime(2025, 1, 1), None, value=-math.inf, stored_value="-Infinity"
            ),
        ),
    ),
    ParameterCase(
        name="gov.value_shapes.numpy_scalars",
        data_type=float,
        values=(
            # numpy.float64 is a float; numpy.int64 and numpy.True_ are read
            # through their item().
            ValueCase(
                datetime(2024, 1, 1),
                datetime(2024, 12, 31),
                value=np.float64(0.25),
                stored_value=0.25,
            ),
            ValueCase(
                datetime(2025, 1, 1),
                datetime(2025, 12, 31),
                value=np.int64(7),
                stored_value=7,
            ),
            ValueCase(datetime(2026, 1, 1), None, value=np.True_, stored_value=True),
        ),
    ),
    ParameterCase(
        name="gov.value_shapes.text",
        data_type=str,
        values=(
            ValueCase(
                datetime(2025, 1, 1),
                datetime(2025, 12, 31),
                value="single",
                stored_value="single",
            ),
            ValueCase(
                datetime(2026, 1, 1),
                None,
                value=TEXT_WITH_COPY_ESCAPES,
                stored_value=TEXT_WITH_COPY_ESCAPES,
            ),
        ),
    ),
    ParameterCase(
        name="gov.value_shapes.filing_status",
        data_type=str,
        values=(
            ValueCase(
                datetime(2025, 1, 1),
                None,
                value=_FilingStatus.JOINT,
                stored_value="JOINT",
            ),
        ),
    ),
    ParameterCase(
        name="gov.value_shapes.effective_date",
        data_type=date,
        values=(
            ValueCase(
                datetime(2024, 1, 1),
                datetime(2024, 12, 31),
                value=date(2024, 4, 6),
                stored_value="2024-04-06",
            ),
            ValueCase(
                datetime(2025, 1, 1),
                None,
                value=datetime(2025, 4, 6, 12, 30),
                stored_value="2025-04-06T12:30:00",
            ),
        ),
    ),
    ParameterCase(
        name="gov.value_shapes.sources",
        data_type=list,
        values=(
            ValueCase(
                datetime(2024, 1, 1),
                datetime(2024, 12, 31),
                value=["employment_income", "self_employment_income"],
                stored_value=["employment_income", "self_employment_income"],
            ),
            ValueCase(
                datetime(2025, 1, 1),
                datetime(2025, 12, 31),
                value=("pension_income",),
                stored_value=["pension_income"],
            ),
            ValueCase(datetime(2026, 1, 1), None, value=[], stored_value=[]),
        ),
    ),
    ParameterCase(
        name="gov.value_shapes.amounts_by_filing_status",
        data_type=dict,
        values=(
            ValueCase(
                datetime(2025, 1, 1),
                datetime(2025, 12, 31),
                value={
                    "SINGLE": 12000.0,
                    "JOINT": 24000,
                    "NESTED": {"enabled": True, "rates": (0.1, None)},
                },
                stored_value={
                    "SINGLE": 12000.0,
                    "JOINT": 24000,
                    "NESTED": {"enabled": True, "rates": [0.1, None]},
                },
            ),
            ValueCase(datetime(2026, 1, 1), None, value={}, stored_value={}),
        ),
    ),
    ParameterCase(
        name="gov.value_shapes.unset",
        data_type=None,
        values=(ValueCase(datetime(2025, 1, 1), None, value=None, stored_value=None),),
    ),
    ParameterCase(
        name="gov.value_shapes.scale[0].rate",
        data_type=float,
        values=(ValueCase(datetime(2025, 1, 1), None, value=0.1, stored_value=0.1),),
    ),
    ParameterCase(
        name="gov.value_shapes.scale[0].threshold",
        data_type=int,
        values=(ValueCase(datetime(2025, 1, 1), None, value=0, stored_value=0),),
    ),
    ParameterCase(
        name="gov.value_shapes.scale[1].rate",
        data_type=float,
        values=(ValueCase(datetime(2025, 1, 1), None, value=0.2, stored_value=0.2),),
    ),
    ParameterCase(
        name="gov.value_shapes.scale[1].threshold",
        data_type=float,
        values=(
            ValueCase(datetime(2025, 1, 1), None, value=50000.0, stored_value=50000.0),
        ),
    ),
)
# The filter value the catalog stores for each region this catalog filters,
# by country and region code.
REGION_FILTER_VALUES = {
    ("us", "state/ca"): "6",
    ("us", "congressional_district/CA-01"): "601",
    ("uk", "country/england"): '["NORTH_EAST","LONDON"]',
    ("uk", "country/wales"): "WALES",
    ("uk", "constituency/W07000081"): "W07000081",
}
US_ACS_LOCAL_URI = "hf://policyengine/us/populace_us_2024_acs_local.h5@fixture"
UK_DENSE_URI = "hf://policyengine/uk/microcosm_uk_2024_25_dense.h5@fixture"


@dataclass(frozen=True, kw_only=True)
class _FilteredRegion:
    """A region that selects its households with one row filter."""

    code: str
    label: str
    region_type: str
    parent_code: str
    filter_field: str
    filter_value: object
    dataset_path: str | None = None
    state_code: str | None = None
    state_name: str | None = None

    def source(self) -> SimpleNamespace:
        """Return the region as the public region registry holds it."""
        return SimpleNamespace(
            code=self.code,
            label=self.label,
            region_type=self.region_type,
            parent_code=self.parent_code,
            dataset_path=self.dataset_path,
            scoping_strategy=SimpleNamespace(
                strategy_type="row_filter",
                variable_name=self.filter_field,
                variable_value=self.filter_value,
                additional_filters={},
            ),
            requires_filter=True,
            state_code=self.state_code,
            state_name=self.state_name,
        )


def _variables() -> list[SimpleNamespace]:
    """Return US variables with each default, possible-value and sum shape."""
    return [
        SimpleNamespace(
            name="filing_status",
            label="Filing status",
            entity="tax_unit",
            description="The tax unit's filing status",
            data_type=str,
            possible_values=["SINGLE", "JOINT"],
            default_value=_FilingStatus.SINGLE,
            adds=None,
            subtracts=None,
        ),
        SimpleNamespace(
            name="is_blind",
            label=None,
            entity="person",
            description=None,
            data_type=bool,
            possible_values=None,
            default_value=False,
            adds=None,
            subtracts=None,
        ),
        SimpleNamespace(
            name="household_net_income",
            label="Household net income",
            entity="household",
            description="Income after taxes and benefits",
            data_type=float,
            possible_values=None,
            default_value=0.0,
            adds=["employment_income"],
            subtracts=["income_tax"],
        ),
    ]


def value_shape_catalog() -> NormalizedCatalog:
    """Return the fixture catalog with every value-shape case added to it."""
    models = source_models()
    us_model = models["us"]
    for variable in _variables():
        us_model.variables.append(variable)
        us_model.variables_by_name[variable.name] = variable
    for node_name in ("gov.value_shapes", *BRACKET_PARAMETER_NODES):
        node = SimpleNamespace(name=node_name, label=None, description=None)
        us_model.parameter_nodes.append(node)
        us_model.parameter_nodes_by_name[node_name] = node
    for case in PARAMETER_CASES:
        parameter = case.source()
        us_model.parameters.append(parameter)
        us_model.parameters_by_name[parameter.name] = parameter
    us_model.region_registry.append(
        _FilteredRegion(
            code="congressional_district/CA-01",
            label="California's 1st congressional district",
            region_type="congressional_district",
            parent_code="state/ca",
            filter_field="congressional_district_geoid",
            filter_value=601,
            dataset_path=US_ACS_LOCAL_URI,
            state_code="CA",
            state_name="California",
        ).source()
    )

    uk_model = models["uk"]
    england = next(
        region
        for region in uk_model.region_registry
        if region.code == "country/england"
    )
    england.scoping_strategy.variable_value = ("NORTH_EAST", "LONDON")
    uk_model.region_registry.extend(
        [
            _FilteredRegion(
                code="country/wales",
                label="Wales",
                region_type="country",
                parent_code="uk",
                filter_field="country",
                filter_value="WALES",
            ).source(),
            _FilteredRegion(
                code="constituency/W07000081",
                label="Ynys Môn",
                region_type="constituency",
                parent_code="uk",
                filter_field="constituency_code_oa",
                filter_value="W07000081",
                dataset_path=UK_DENSE_URI,
            ).source(),
        ]
    )
    return extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
    )
