"""Direct Black-Scholes pricing for European, non-dividend-paying options."""

from math import erfc, exp, isfinite, log, sqrt

from quant.contracts import MarketSnapshot, OptionContract, OptionType
from quant.conventions import act365f
from quant.errors import ContractValidationError, PricingError

BOUND_RELATIVE_TOLERANCE = 1e-10


def pricing_inputs(contract: OptionContract, market: MarketSnapshot) -> tuple[float, float]:
    """Return maturity and discounted strike after common boundary checks."""
    if not isinstance(contract, OptionContract) or not isinstance(market, MarketSnapshot):
        raise ContractValidationError("pricing requires an OptionContract and MarketSnapshot")
    if (contract.underlying, contract.currency) != (market.underlying, market.currency):
        raise ContractValidationError("contract and market currency/underlying must match")
    maturity = act365f(market.valuation_date, contract.expiry)
    try:
        discounted_strike = contract.strike * exp(-market.rate * maturity)
    except OverflowError as exc:
        raise PricingError("discounted strike overflowed") from exc
    if not isfinite(discounted_strike):
        raise PricingError("discounted strike is not finite")
    return maturity, discounted_strike


def price_bounds(contract: OptionContract, market: MarketSnapshot) -> tuple[float, float]:
    """No-arbitrage per-unit bounds under q=0 and a flat continuous rate."""
    _, discounted_strike = pricing_inputs(contract, market)
    if contract.option_type is OptionType.CALL:
        return max(market.spot - discounted_strike, 0.0), market.spot
    return max(discounted_strike - market.spot, 0.0), discounted_strike


def checked_price(value: object, contract: OptionContract, market: MarketSnapshot) -> float:
    """Fail explicitly on invalid results; retain small positive round-off errors.

    Negative prices always fail. Other bound errors up to 1e-10 times the larger
    of spot, discounted strike and one are tolerated without altering the value.
    No failed calculation is converted to a zero price.
    """
    if type(value) not in (int, float):
        raise PricingError("price must be a finite number")
    try:
        value = float(value)
    except OverflowError as exc:
        raise PricingError("price overflowed") from exc
    if not isfinite(value) or value < 0:
        raise PricingError("price must be finite and nonnegative")
    lower, upper = price_bounds(contract, market)
    tolerance = BOUND_RELATIVE_TOLERANCE * max(1.0, market.spot, upper)
    if value < lower - tolerance or value > upper + tolerance:
        raise PricingError(f"price {value} violates bounds [{lower}, {upper}]")
    return value


def _normal_cdf(value: float) -> float:
    return 0.5 * erfc(-value / sqrt(2.0))


def black_scholes(contract: OptionContract, market: MarketSnapshot) -> float:
    """Per-unit USD price; rate and sigma0 use decimal annual units."""
    maturity, discounted_strike = pricing_inputs(contract, market)
    try:
        standard_deviation = market.sigma0 * sqrt(maturity)
        if not isfinite(standard_deviation) or standard_deviation <= 0:
            raise PricingError("total standard deviation is not finite and positive")
        # Difference of logs avoids overflowing the otherwise valid S/K ratio.
        d1 = (
            log(market.spot)
            - log(contract.strike)
            + market.rate * maturity
            + 0.5 * standard_deviation * standard_deviation
        ) / standard_deviation
        d2 = d1 - standard_deviation
        if not isfinite(d1) or not isfinite(d2):
            raise PricingError("Black-Scholes d1/d2 are not finite")
        if contract.option_type is OptionType.CALL:
            value = market.spot * _normal_cdf(d1) - discounted_strike * _normal_cdf(d2)
        else:
            value = discounted_strike * _normal_cdf(-d2) - market.spot * _normal_cdf(-d1)
    except (OverflowError, ZeroDivisionError) as exc:
        raise PricingError("Black-Scholes arithmetic overflow or underflow") from exc
    return checked_price(value, contract, market)
