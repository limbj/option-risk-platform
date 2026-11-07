from datetime import date

import pytest

from quant.contracts import OptionContract, OptionType, Position, Side
from quant.errors import ContractValidationError, PricingError
from quant.portfolio import PositionValuation, aggregate_portfolio, position_value, stress_pnl

CONTRACT = OptionContract(OptionType.CALL, 100, date(2028, 1, 1))


def total(values, source="heston/model-v1/laguerre-144"):
    return aggregate_portfolio(
        [PositionValuation(str(i), value=value) for i, value in enumerate(values)],
        [str(i) for i in range(len(values))],
        source=source,
    )


def test_long_short_quantity_multiplier_and_zero_price():
    long = Position(CONTRACT, Side.LONG, 3, 100)
    short = Position(CONTRACT, Side.SHORT, -3, 100)
    assert position_value(long, 2.5) == 750
    assert position_value(short, 2.5) == -750
    assert position_value(short, 0) == 0


def test_complete_total_uses_stable_sum():
    result = total([1e16, 1, -1e16])
    assert result.complete
    assert result.total == 1
    assert result.completed_count == 3


@pytest.mark.parametrize("failed", [False, True])
def test_missing_or_failed_result_never_becomes_zero_or_partial_total(failed):
    cells = [PositionValuation("a", value=10)]
    if failed:
        cells.append(PositionValuation("b", error="reference integration failed"))
    result = aggregate_portfolio(cells, ["a", "b"], source="reference-v1")
    assert result.total is None
    assert not result.complete
    assert result.completed_count == 1
    assert result.errors
    base = aggregate_portfolio(
        [PositionValuation("a", value=10), PositionValuation("b", value=20)],
        ["a", "b"],
        source="reference-v1",
    )
    assert stress_pnl(base, result) is None
    assert stress_pnl(result, base) is None


def test_stress_pnl_sign_and_like_for_like_sources():
    assert stress_pnl(total([100, -30]), total([80, -40])) == -30
    with pytest.raises(ContractValidationError, match="model/engine/version"):
        stress_pnl(total([100]), total([110], source="ml-v1"))


def test_duplicate_and_unexpected_cells_rejected():
    with pytest.raises(ContractValidationError):
        aggregate_portfolio(
            [PositionValuation("a", value=1), PositionValuation("a", value=2)],
            ["a"],
            source="reference",
        )
    with pytest.raises(ContractValidationError):
        aggregate_portfolio([PositionValuation("b", value=1)], ["a"], source="reference")


def test_failure_cannot_have_a_price_and_an_error():
    with pytest.raises(ContractValidationError):
        PositionValuation("a", value=0, error="failure")


def test_position_and_aggregate_overflow_fail():
    with pytest.raises(PricingError):
        position_value(Position(CONTRACT, Side.LONG, 2, 1e200), 1e200)
    with pytest.raises(PricingError):
        total([1e308, 1e308])
