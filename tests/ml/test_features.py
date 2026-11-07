from dataclasses import asdict, replace
from datetime import date

import pytest

from ml.features import (
    DEFAULT_SPEC,
    DOMAIN,
    UnsupportedInput,
    features,
    validate_features,
    validate_spec,
)
from quant.contracts import MarketSnapshot, OptionContract, OptionType


def test_feature_order_and_units_are_explicit():
    contract = OptionContract(OptionType.CALL, 100, date(2027, 1, 1))
    market = MarketSnapshot(date(2026, 1, 1), 100, -0.01, 0.2)
    assert features(contract, market) == [0, 1, -0.01, 0.2]


@pytest.mark.parametrize(
    "axis,value", [(0, 0.5), (1, 0.001), (2, 0.2), (3, 0.8), (3, float("nan"))]
)
def test_unsupported_feature_regions_are_explicit(axis, value):
    row = [0, 1, 0.03, 0.2]
    row[axis] = value
    with pytest.raises(UnsupportedInput, match="outside supported"):
        validate_features(row, DOMAIN)


def test_model_parameters_must_match_the_artifact_exactly():
    validate_spec(DEFAULT_SPEC, asdict(DEFAULT_SPEC))
    with pytest.raises(UnsupportedInput, match="specification differs"):
        validate_spec(replace(DEFAULT_SPEC, theta=0.09), asdict(DEFAULT_SPEC))
