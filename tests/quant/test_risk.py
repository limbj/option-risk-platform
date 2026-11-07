from dataclasses import replace
from datetime import date
from math import erfc, exp, log, pi, sqrt

import pytest

from quant.contracts import HestonModelSpec, MarketSnapshot, OptionContract, OptionType
from quant.errors import ContractValidationError, PricingError
from quant.heston import HestonPricer
from quant.pricing import black_scholes
from quant.risk import sensitivities

MARKET = MarketSnapshot(date(2027, 1, 1), 100, 0.05, 0.2)
CALL = OptionContract(OptionType.CALL, 100, date(2028, 1, 1))


@pytest.mark.parametrize("option_type", list(OptionType))
def test_central_differences_match_analytic_black_scholes_derivatives(option_type):
    contract = replace(CALL, option_type=option_type)
    result = sensitivities(contract, MARKET, black_scholes)
    d1 = (log(MARKET.spot / CALL.strike) + MARKET.rate + 0.5 * MARKET.v0) / MARKET.sigma0
    density = exp(-0.5 * d1**2) / sqrt(2 * pi)
    expected_delta = 0.5 * erfc(-d1 / sqrt(2)) - (option_type is OptionType.PUT)
    assert result.delta == pytest.approx(expected_delta, abs=1e-8)
    assert result.gamma == pytest.approx(density / (MARKET.spot * MARKET.sigma0), abs=1e-8)
    assert result.initial_volatility_sensitivity == pytest.approx(MARKET.spot * density, abs=1e-5)
    assert result.initial_volatility_per_percentage_point == pytest.approx(
        MARKET.spot * density * 0.01, abs=1e-7
    )
    assert result.spot_bump == 0.01
    assert result.sigma0_bump == 0.0001


def test_heston_bump_convergence_and_fixed_model_settings():
    spec = HestonModelSpec(2, 0.04, 0.3, -0.7)
    pricer = HestonPricer(spec)
    coarse = sensitivities(CALL, MARKET, pricer.price, spot_relative_bump=2e-4, sigma0_bump=2e-4)
    fine = sensitivities(CALL, MARKET, pricer.price)
    assert coarse.delta == pytest.approx(fine.delta, abs=1e-7)
    assert coarse.gamma == pytest.approx(fine.gamma, abs=1e-8)
    assert coarse.initial_volatility_sensitivity == pytest.approx(
        fine.initial_volatility_sensitivity, abs=2e-6
    )
    assert pricer.spec == spec
    assert MARKET.sigma0 == 0.2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"spot_relative_bump": 0},
        {"spot_relative_bump": 1},
        {"spot_relative_bump": 1e-30},
        {"sigma0_bump": 0.2},
        {"sigma0_bump": True},
        {"sigma0_bump": float("nan")},
    ],
)
def test_invalid_central_bumps_rejected(kwargs):
    with pytest.raises(ContractValidationError):
        sensitivities(CALL, MARKET, black_scholes, **kwargs)


def test_bad_price_does_not_create_fake_zero_sensitivities():
    with pytest.raises(PricingError):
        sensitivities(CALL, MARKET, lambda *_: float("nan"))


def test_underlying_pricing_failure_propagates():
    def fail(*_):
        raise PricingError("reference unavailable")

    with pytest.raises(PricingError, match="reference unavailable"):
        sensitivities(CALL, MARKET, fail)
