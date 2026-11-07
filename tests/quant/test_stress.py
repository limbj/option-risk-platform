from datetime import date

import pytest

from quant.contracts import MarketSnapshot, StressScenario
from quant.errors import ContractValidationError
from quant.stress import apply_stress

MARKET = MarketSnapshot(date(2027, 1, 1), 100, 0.03, 0.2)


def test_stress_units_and_unchanged_calendar_identity():
    stressed = apply_stress(MARKET, StressScenario("combined", -10, 5, 100))
    assert stressed.spot == pytest.approx(90)
    assert stressed.sigma0 == pytest.approx(0.25)
    assert stressed.v0 == pytest.approx(0.0625)
    assert stressed.rate == pytest.approx(0.04)
    assert stressed.valuation_date == MARKET.valuation_date
    assert stressed.currency == MARKET.currency
    assert stressed.underlying == MARKET.underlying
    assert MARKET.sigma0 == 0.2


def test_identity_scenario_returns_equal_new_snapshot():
    stressed = apply_stress(MARKET, StressScenario("base"))
    assert stressed == MARKET
    assert stressed is not MARKET


def test_negative_rates_are_valid_stress_outcomes():
    assert apply_stress(MARKET, StressScenario("rates down", rate_shock_bp=-500)).rate == (
        pytest.approx(-0.02)
    )


@pytest.mark.parametrize("shock", [-20, -25])
def test_invalid_volatility_shocks_fail_without_clamping(shock):
    with pytest.raises(ContractValidationError):
        apply_stress(MARKET, StressScenario("invalid", sigma0_shock_pp=shock))


def test_reverse_shocks_recover_rate_and_initial_volatility():
    up = apply_stress(MARKET, StressScenario("up", sigma0_shock_pp=5, rate_shock_bp=100))
    back = apply_stress(up, StressScenario("down", sigma0_shock_pp=-5, rate_shock_bp=-100))
    assert back.sigma0 == pytest.approx(MARKET.sigma0)
    assert back.rate == pytest.approx(MARKET.rate)
