"""Test pandas 3.0 compatibility with enum encoding."""

import pandas as pd
from policyengine_core.enums import Enum


class SampleEnum(Enum):
    VALUE_A = "value_a"
    VALUE_B = "value_b"


def test_enum_encode_with_pandas_series():
    """Test that Enum.encode works with pandas Series."""
    enum_items = [SampleEnum.VALUE_A, SampleEnum.VALUE_B, SampleEnum.VALUE_A]
    series = pd.Series(enum_items)

    encoded = SampleEnum.encode(series)

    assert len(encoded) == 3
    assert list(encoded) == [0, 1, 0]
