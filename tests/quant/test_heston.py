from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from math import exp, sqrt

import pytest
import QuantLib as ql

from quant.contracts import HestonModelSpec, MarketSnapshot, OptionContract, OptionType
from quant.errors import ContractValidationError, PricingError
from quant.heston import HestonPricer
from quant.pricing import black_scholes, price_bounds

MARKET = MarketSnapshot(date(2027, 1, 1), 100.0, 0.05, 0.2)
CALL = OptionContract(OptionType.CALL, 100, date(2028, 1, 1))
SPEC = HestonModelSpec(2, 0.04, 0.3, -0.7)


@pytest.mark.parametrize("option_type", list(OptionType))
@pytest.mark.parametrize("spot", [80.0, 100.0, 120.0])
def test_low_vol_of_variance_limit_matches_black_scholes(option_type, spot):
    # Independent limit: with v0=theta and xi -> 0 variance becomes constant.
    # QuantLib's upstream testAnalyticVsBlack uses this same mathematical limit.
    pricer = HestonPricer(HestonModelSpec(5, MARKET.v0, 1e-4, 0))
    contract, market = replace(CALL, option_type=option_type), replace(MARKET, spot=spot)
    assert pricer.price(contract, market) == pytest.approx(
        black_scholes(contract, market), abs=2e-7
    )


def test_deterministic_mean_reverting_variance_limit():
    # xi -> 0, rho=0: integrated variance is known without a Heston engine.
    spec = HestonModelSpec(2, 0.09, 1e-4, 0)
    average_variance = spec.theta + (MARKET.v0 - spec.theta) * (1 - exp(-spec.kappa)) / spec.kappa
    equivalent_market = replace(MARKET, sigma0=sqrt(average_variance))
    expected = black_scholes(CALL, equivalent_market)
    assert HestonPricer(spec).price(CALL, MARKET) == pytest.approx(expected, abs=2e-7)


@pytest.mark.parametrize(
    "spot,days,rate", [(80, 365, -0.02), (100, 1, 0.03), (100, 30, 0), (120, 730, 0.08)]
)
def test_heston_parity_bounds_and_quadrature_convergence(spot, days, rate):
    market = replace(MARKET, spot=spot, rate=rate)
    contract = replace(CALL, expiry=market.valuation_date + timedelta(days=days))
    put = replace(contract, option_type=OptionType.PUT)
    pricer = HestonPricer(SPEC, 144)
    call_price, put_price = pricer.price(contract, market), pricer.price(put, market)
    assert call_price - put_price == pytest.approx(spot - 100 * exp(-rate * days / 365), abs=1e-10)
    for option, price in [(contract, call_price), (put, put_price)]:
        lower, upper = price_bounds(option, market)
        assert lower - 1e-10 <= price <= upper + 1e-10
        assert price == pytest.approx(HestonPricer(SPEC, 192).price(option, market), abs=2e-8)


def test_reused_engine_updates_all_market_inputs_and_restores_base():
    pricer = HestonPricer(SPEC)
    base = pricer.price(CALL, MARKET)
    engine = pricer._engine
    for market in [
        replace(MARKET, spot=90),
        replace(MARKET, rate=-0.02),
        replace(MARKET, sigma0=0.3),
        replace(MARKET, spot=110, rate=0.08, sigma0=0.4),
    ]:
        assert pricer.price(CALL, market) == pytest.approx(
            HestonPricer(SPEC).price(CALL, market), abs=1e-12
        )
        assert pricer._engine is engine
    assert pricer.price(CALL, MARKET) == pytest.approx(base, abs=1e-12)
    assert pricer.spec == SPEC


def test_changed_date_rebuilds_curves_and_matches_fresh_engine():
    pricer = HestonPricer(SPEC)
    base = pricer.price(CALL, MARKET)
    new_market = replace(MARKET, valuation_date=date(2027, 6, 1))
    new = pricer.price(CALL, new_market)
    assert new != base
    assert new == pytest.approx(HestonPricer(SPEC).price(CALL, new_market), abs=1e-12)
    assert pricer.price(CALL, MARKET) == pytest.approx(base, abs=1e-12)


def test_evaluation_date_restored_on_success_and_error(monkeypatch):
    with ql.SavedSettings():
        ql.Settings.instance().evaluationDate = ql.Date(17, 2, 2025)
        original = ql.Settings.instance().evaluationDate
        pricer = HestonPricer(SPEC)
        pricer.price(CALL, MARKET)
        assert ql.Settings.instance().evaluationDate == original

        def fail(_):
            raise RuntimeError("injected reference failure")

        monkeypatch.setattr(pricer, "_prepare_market", fail)
        with pytest.raises(PricingError, match="injected reference failure"):
            pricer.price(CALL, MARKET)
        assert ql.Settings.instance().evaluationDate == original


def test_concurrent_adapter_calls_do_not_cross_contaminate_dates():
    inputs = [
        replace(MARKET, valuation_date=date(2027, month, 1), spot=90 + month)
        for month in range(1, 10)
    ]
    expected = [HestonPricer(SPEC).price(CALL, market) for market in inputs]
    shared_pricer = HestonPricer(SPEC)
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(lambda market: shared_pricer.price(CALL, market), inputs))
    assert actual == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("order", [True, 0, 15, 193, 144.0])
def test_invalid_quadrature_configuration_rejected(order):
    with pytest.raises(ContractValidationError):
        HestonPricer(SPEC, order)


def test_quantlib_calendar_limit_is_explicit_failure():
    with pytest.raises(PricingError):
        HestonPricer(SPEC).price(
            replace(CALL, expiry=date(2301, 1, 1)), replace(MARKET, valuation_date=date(2300, 1, 1))
        )
