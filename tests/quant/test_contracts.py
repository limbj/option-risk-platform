from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from quant.contracts import (
    HestonModelSpec,
    MarketSnapshot,
    OptionContract,
    OptionType,
    Position,
    Side,
    StressScenario,
)
from quant.errors import ContractValidationError


def contract(**changes):
    values = {"option_type": OptionType.CALL, "strike": 100.0, "expiry": date(2027, 1, 1)}
    return OptionContract(**(values | changes))


def market(**changes):
    values = {"valuation_date": date(2026, 1, 1), "spot": 100.0, "rate": 0.03, "sigma0": 0.2}
    return MarketSnapshot(**(values | changes))


INVALID_NUMBERS = [float("nan"), float("inf"), -float("inf"), True, False, "0.2", None]


@pytest.mark.parametrize("option_type", [OptionType.CALL, OptionType.PUT])
def test_european_contracts_accept_call_and_put(option_type):
    result = contract(option_type=option_type)
    assert result.option_type is option_type
    assert result.underlying == "SYNTH_INDEX"
    assert result.currency == "USD"


@pytest.mark.parametrize("option_type", ["call", "put", "american", 1, None])
def test_domain_contracts_require_an_explicit_option_type(option_type):
    with pytest.raises(ContractValidationError):
        contract(option_type=option_type)


@pytest.mark.parametrize("strike", [*INVALID_NUMBERS, 0.0, -1.0])
def test_strike_must_be_positive_and_finite(strike):
    with pytest.raises(ContractValidationError):
        contract(strike=strike)


@pytest.mark.parametrize("field", ["spot", "sigma0"])
@pytest.mark.parametrize("value", [*INVALID_NUMBERS, 0.0, -1.0])
def test_market_positive_fields_reject_invalid_values(field, value):
    with pytest.raises(ContractValidationError):
        market(**{field: value})


@pytest.mark.parametrize("value", INVALID_NUMBERS)
def test_rate_must_be_numeric_and_finite(value):
    with pytest.raises(ContractValidationError):
        market(rate=value)


def test_negative_interest_rates_and_decimal_annual_volatility_are_supported():
    snapshot = market(rate=-0.01, sigma0=0.2)
    assert snapshot.rate == -0.01
    assert snapshot.v0 == pytest.approx(0.04)


@pytest.mark.parametrize("sigma0", [1e200, 1e-200])
def test_initial_variance_must_not_overflow_or_underflow_to_zero(sigma0):
    with pytest.raises(ContractValidationError):
        market(sigma0=sigma0)


@pytest.mark.parametrize("constructor", [contract, market])
@pytest.mark.parametrize(
    ("field", "value"),
    [("currency", "EUR"), ("currency", "usd"), ("currency", None), ("underlying", "SPX")],
)
def test_stage_one_rejects_unsupported_currencies_and_underlyings(constructor, field, value):
    with pytest.raises(ContractValidationError):
        constructor(**{field: value})


@pytest.mark.parametrize("value", ["2027-01-01", datetime(2027, 1, 1), None])
def test_contract_and_market_dates_must_be_date_objects(value):
    with pytest.raises(ContractValidationError):
        contract(expiry=value)
    with pytest.raises(ContractValidationError):
        market(valuation_date=value)


@pytest.mark.parametrize(("side", "quantity"), [(Side.LONG, 3), (Side.SHORT, -3)])
def test_position_preserves_signed_quantity_and_explicit_multiplier(side, quantity):
    position = Position(contract(), side=side, quantity=quantity, multiplier=100.0)
    position.validate_for(market())
    assert position.quantity == quantity
    assert position.multiplier == 100.0


@pytest.mark.parametrize(
    ("side", "quantity"),
    [
        (Side.LONG, -1),
        (Side.SHORT, 1),
        (Side.LONG, 0),
        (Side.SHORT, 0),
        (Side.LONG, True),
        (Side.LONG, 1.0),
        (Side.LONG, "1"),
        (Side.LONG, float("nan")),
        ("long", 1),
        (None, 1),
    ],
)
def test_quantity_is_a_nonzero_integer_with_a_consistent_explicit_side(side, quantity):
    with pytest.raises(ContractValidationError):
        Position(contract(), side=side, quantity=quantity, multiplier=100.0)


@pytest.mark.parametrize("multiplier", [*INVALID_NUMBERS, 0, -100])
def test_multiplier_must_be_positive_finite_and_independent_of_side(multiplier):
    with pytest.raises(ContractValidationError):
        Position(contract(), side=Side.SHORT, quantity=-1, multiplier=multiplier)


@pytest.mark.parametrize("expiry", [date(2026, 1, 1), date(2025, 12, 31)])
def test_expired_and_same_day_contracts_are_rejected_at_the_valuation_boundary(expiry):
    position = Position(contract(expiry=expiry), side=Side.LONG, quantity=1, multiplier=1)
    with pytest.raises(ContractValidationError):
        position.validate_for(market())


def test_a_position_requires_a_validated_contract():
    with pytest.raises(ContractValidationError):
        Position({}, side=Side.LONG, quantity=1, multiplier=1)


@given(quantity=st.integers(min_value=1, max_value=1_000_000))
def test_long_and_short_quantities_keep_equal_and_opposite_exposure(quantity):
    long = Position(contract(), Side.LONG, quantity, 100)
    short = Position(contract(), Side.SHORT, -quantity, 100)
    assert long.quantity * long.multiplier == -(short.quantity * short.multiplier)


@pytest.mark.parametrize("field", ["kappa", "theta", "xi"])
@pytest.mark.parametrize("value", [*INVALID_NUMBERS, 0, -1])
def test_heston_model_requires_positive_finite_variance_parameters(field, value):
    values = {"kappa": 2.0, "theta": 0.04, "xi": 0.3, "rho": -0.7}
    with pytest.raises(ContractValidationError):
        HestonModelSpec(**(values | {field: value}))


@pytest.mark.parametrize("rho", [*INVALID_NUMBERS, -1.01, 1.01])
def test_heston_correlation_is_finite_and_bounded(rho):
    with pytest.raises(ContractValidationError):
        HestonModelSpec(kappa=2, theta=0.04, xi=0.3, rho=rho)


@pytest.mark.parametrize("rho", [-1.0, 0.0, 1.0])
def test_correlation_endpoints_are_accepted_without_imposing_the_feller_condition(rho):
    spec = HestonModelSpec(kappa=1.0, theta=0.04, xi=1.0, rho=rho)
    assert 2 * spec.kappa * spec.theta < spec.xi**2
    assert spec.rho == rho


def test_stress_units_are_explicit_and_have_distinct_conversions():
    scenario = StressScenario("up", spot_shock_pct=10, sigma0_shock_pp=5, rate_shock_bp=100)
    scenario.validate_for(market())
    assert scenario.spot_relative_change == pytest.approx(0.10)
    assert scenario.sigma0_change == pytest.approx(0.05)
    assert scenario.rate_change == pytest.approx(0.01)
    assert market().sigma0 + scenario.sigma0_change == pytest.approx(0.25)


def test_instantaneous_validation_does_not_mutate_market_date_or_model_inputs():
    snapshot = market()
    original = replace(snapshot)
    scenario = StressScenario("down", spot_shock_pct=-10, sigma0_shock_pp=-5, rate_shock_bp=-100)
    scenario.validate_for(snapshot)
    assert snapshot == original
    assert snapshot.valuation_date == date(2026, 1, 1)
    assert snapshot.sigma0 == 0.2


@pytest.mark.parametrize("field", ["spot_shock_pct", "sigma0_shock_pp", "rate_shock_bp"])
@pytest.mark.parametrize("value", INVALID_NUMBERS)
def test_stress_shocks_must_be_finite_numbers(field, value):
    with pytest.raises(ContractValidationError):
        StressScenario("invalid", **{field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"spot_shock_pct": -100},
        {"spot_shock_pct": -101},
        {"sigma0_shock_pp": -20},
        {"sigma0_shock_pp": -21},
        {"sigma0_shock_pp": 1e200},
    ],
)
def test_invalid_stressed_markets_are_rejected_instead_of_clamped(changes):
    with pytest.raises(ContractValidationError):
        StressScenario("invalid", **changes).validate_for(market())


def test_stressed_spot_and_rate_overflow_are_rejected():
    with pytest.raises(ContractValidationError):
        StressScenario("overflow", spot_shock_pct=100).validate_for(market(spot=1e308))
    with pytest.raises(ContractValidationError):
        StressScenario("overflow", rate_shock_bp=1e308).validate_for(market(rate=1.7976e308))


@pytest.mark.parametrize("field", ["spot_shock_pct", "sigma0_shock_pp", "rate_shock_bp"])
def test_nonzero_shocks_cannot_silently_underflow_to_zero_during_conversion(field):
    with pytest.raises(ContractValidationError):
        StressScenario("underflow", **{field: 5e-324})


def test_unrepresentable_integer_inputs_raise_a_financial_validation_error():
    huge = 10**1000
    with pytest.raises(ContractValidationError):
        market(spot=huge)
    with pytest.raises(ContractValidationError):
        Position(contract(), Side.LONG, huge, 1)


@pytest.mark.parametrize("name", ["", "   ", None, 1])
def test_stress_scenario_names_must_be_nonempty_text(name):
    with pytest.raises(ContractValidationError):
        StressScenario(name)


@pytest.mark.parametrize(
    ("value", "field", "replacement"),
    [
        (contract(), "strike", 200),
        (market(), "spot", 200),
        (Position(contract(), Side.LONG, 1, 100), "quantity", 2),
        (HestonModelSpec(2, 0.04, 0.3, -0.7), "theta", 0.09),
        (StressScenario("base"), "spot_shock_pct", 10),
    ],
)
def test_financial_inputs_cannot_be_changed_after_validation(value, field, replacement):
    with pytest.raises(FrozenInstanceError):
        setattr(value, field, replacement)
