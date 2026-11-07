from dataclasses import replace
from datetime import date, timedelta
from math import exp

import pytest
import QuantLib as ql

from quant.contracts import MarketSnapshot, OptionContract, OptionType
from quant.errors import ContractValidationError, PricingError
from quant.pricing import black_scholes, checked_price, price_bounds

MARKET = MarketSnapshot(date(2027, 1, 1), 100.0, 0.05, 0.2)
CALL = OptionContract(OptionType.CALL, 100.0, date(2028, 1, 1))


@pytest.mark.parametrize(
    ("option_type", "expected"),
    [(OptionType.CALL, 10.450583572185565), (OptionType.PUT, 5.573526022256971)],
)
def test_independent_black_scholes_reference(option_type, expected):
    # Standard S=K=100, T=1, r=5%, sigma=20%, q=0 reference values.
    assert black_scholes(replace(CALL, option_type=option_type), MARKET) == pytest.approx(
        expected, abs=1e-12
    )


@pytest.mark.parametrize("spot", [50.0, 100.0, 150.0])
@pytest.mark.parametrize("days", [1, 30, 365, 730])
@pytest.mark.parametrize("rate", [-0.05, 0.0, 0.08])
def test_parity_and_no_arbitrage_bounds(spot, days, rate):
    market = replace(MARKET, spot=spot, rate=rate)
    call = replace(CALL, expiry=market.valuation_date + timedelta(days=days))
    put = replace(call, option_type=OptionType.PUT)
    call_price, put_price = black_scholes(call, market), black_scholes(put, market)
    assert call_price - put_price == pytest.approx(
        spot - call.strike * exp(-rate * days / 365), abs=1e-11
    )
    for contract, price in [(call, call_price), (put, put_price)]:
        lower, upper = price_bounds(contract, market)
        assert lower - 1e-11 <= price <= upper + 1e-11


def test_maturity_boundary_rejected():
    with pytest.raises(ContractValidationError):
        black_scholes(replace(CALL, expiry=MARKET.valuation_date), MARKET)


@pytest.mark.parametrize("price", [float("nan"), float("inf"), -1e-15, 200.0, True])
def test_invalid_engine_output_is_not_replaced_with_zero(price):
    with pytest.raises(PricingError):
        checked_price(price, CALL, MARKET)


def test_discount_overflow_is_explicit_failure():
    with pytest.raises(PricingError, match="discounted strike"):
        black_scholes(CALL, replace(MARKET, rate=-1000))


def test_extreme_moneyness_avoids_overflowing_spot_strike_ratio():
    assert black_scholes(replace(CALL, strike=1e-200), replace(MARKET, spot=1e200)) == 1e200


@pytest.mark.parametrize("option_type", list(OptionType))
@pytest.mark.parametrize(
    "spot,rate,sigma0,days",
    [(80, -0.02, 0.35, 30), (100, 0.05, 0.2, 365), (120, 0.01, 0.1, 1), (100, 0, 0.8, 730)],
)
def test_independent_quantlib_black_scholes_cross_check(option_type, spot, rate, sigma0, days):
    market = replace(MARKET, spot=spot, rate=rate, sigma0=sigma0)
    contract = replace(
        CALL, option_type=option_type, expiry=market.valuation_date + timedelta(days=days)
    )
    with ql.SavedSettings():
        today = ql.Date(1, 1, 2027)
        ql.Settings.instance().evaluationDate = today
        dc = ql.Actual365Fixed()
        process = ql.BlackScholesMertonProcess(
            ql.QuoteHandle(ql.SimpleQuote(spot)),
            ql.YieldTermStructureHandle(ql.FlatForward(today, 0, dc)),
            ql.YieldTermStructureHandle(ql.FlatForward(today, rate, dc)),
            ql.BlackVolTermStructureHandle(
                ql.BlackConstantVol(today, ql.NullCalendar(), sigma0, dc)
            ),
        )
        option = ql.VanillaOption(
            ql.PlainVanillaPayoff(
                ql.Option.Call if option_type is OptionType.CALL else ql.Option.Put, 100
            ),
            ql.EuropeanExercise(today + days),
        )
        option.setPricingEngine(ql.AnalyticEuropeanEngine(process))
        expected = option.NPV()
    assert black_scholes(contract, market) == pytest.approx(expected, abs=1e-11)
