"""Reference-engine, central bump/reprice sensitivities with explicit units."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from math import isfinite

from quant._validation import finite_number, positive_number
from quant.contracts import MarketSnapshot, OptionContract
from quant.errors import ContractValidationError, PricingError
from quant.pricing import checked_price, pricing_inputs

Pricer = Callable[[OptionContract, MarketSnapshot], float]


@dataclass(frozen=True, slots=True)
class Sensitivities:
    """Per-unit price derivatives, before signed quantity and multiplier.

    delta: USD option value per one-unit spot increase.
    gamma: USD option value per squared one-unit spot increase.
    initial_volatility_sensitivity: USD per 1.0 decimal annual sigma0 increase;
    multiply by 0.01 to display per one volatility percentage point.
    spot_bump is the absolute spot increment; sigma0_bump is a decimal increment.
    """

    delta: float
    gamma: float
    initial_volatility_sensitivity: float
    spot_bump: float
    sigma0_bump: float

    def __post_init__(self) -> None:
        for field in ("delta", "gamma", "initial_volatility_sensitivity"):
            object.__setattr__(self, field, finite_number(getattr(self, field), field))
        for field in ("spot_bump", "sigma0_bump"):
            object.__setattr__(self, field, positive_number(getattr(self, field), field))

    @property
    def initial_volatility_per_percentage_point(self) -> float:
        return self.initial_volatility_sensitivity * 0.01


def sensitivities(
    contract: OptionContract,
    market: MarketSnapshot,
    pricer: Pricer,
    *,
    spot_relative_bump: float = 1e-4,
    sigma0_bump: float = 1e-4,
) -> Sensitivities:
    """Central finite differences, fixed dates/rate/model parameters.

    Default spot bump is 0.01% of spot; sigma0 bump is 0.0001 (0.01 vol points).
    Invalid/nonrepresentable two-sided bumps fail instead of changing stencil.
    For Heston pass HestonPricer.price so only initial variance changes with
    sigma0; theta, kappa, xi and rho remain fixed.
    """
    pricing_inputs(contract, market)
    if not callable(pricer):
        raise ContractValidationError("pricer must be callable")
    relative = positive_number(spot_relative_bump, "spot_relative_bump")
    volatility_bump = positive_number(sigma0_bump, "sigma0_bump")
    spot_bump = positive_number(market.spot * relative, "spot_bump")
    if relative >= 1 or volatility_bump >= market.sigma0:
        raise ContractValidationError("central bumps must keep spot and sigma0 positive")
    if spot_bump * spot_bump == 0 or not isfinite(spot_bump * spot_bump):
        raise ContractValidationError("squared spot bump is not representable")
    for value, bump in [(market.spot, spot_bump), (market.sigma0, volatility_bump)]:
        if value + bump == value or value - bump == value:
            raise ContractValidationError("bump is too small to change its floating-point input")

    def price(snapshot: MarketSnapshot) -> float:
        return checked_price(pricer(contract, snapshot), contract, snapshot)

    base = price(market)
    spot_up = price(replace(market, spot=market.spot + spot_bump))
    spot_down = price(replace(market, spot=market.spot - spot_bump))
    vol_up = price(replace(market, sigma0=market.sigma0 + volatility_bump))
    vol_down = price(replace(market, sigma0=market.sigma0 - volatility_bump))
    delta = (spot_up - spot_down) / (2.0 * spot_bump)
    gamma = (spot_up - 2.0 * base + spot_down) / (spot_bump * spot_bump)
    initial_volatility = (vol_up - vol_down) / (2.0 * volatility_bump)
    if not all(isfinite(value) for value in (delta, gamma, initial_volatility)):
        raise PricingError("finite-difference sensitivity overflowed")
    return Sensitivities(delta, gamma, initial_volatility, spot_bump, volatility_bump)
