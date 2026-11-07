"""Immutable financial contracts for the initial synthetic, USD-only profile.

The supported options are European and cash settled, with no dividends (q=0).
Pricing, aggregation and stress modules share the validated inputs defined here.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from quant._validation import (
    calendar_date,
    convert_units,
    finite_number,
    positive_number,
    supported_identity,
    variance_from_sigma,
)
from quant.conventions import act365f
from quant.errors import ContractValidationError


class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True, slots=True)
class OptionContract:
    """Per-unit contract: strike is USD per underlying unit, expiry a date."""

    option_type: OptionType
    strike: float
    expiry: date
    underlying: str = "SYNTH_INDEX"
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not isinstance(self.option_type, OptionType):
            raise ContractValidationError("option_type must be an OptionType")
        object.__setattr__(self, "strike", positive_number(self.strike, "strike"))
        calendar_date(self.expiry, "expiry")
        supported_identity(self.underlying, self.currency)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Spot in USD, continuously compounded annual rate, decimal annual sigma0.

    For example rate=0.03 means 3%, sigma0=0.20 means 20%. The flat rate may
    be negative. Initial volatility and its derived variance must be positive.
    """

    valuation_date: date
    spot: float
    rate: float
    sigma0: float
    underlying: str = "SYNTH_INDEX"
    currency: str = "USD"

    def __post_init__(self) -> None:
        calendar_date(self.valuation_date, "valuation_date")
        object.__setattr__(self, "spot", positive_number(self.spot, "spot"))
        object.__setattr__(self, "rate", finite_number(self.rate, "rate"))
        object.__setattr__(self, "sigma0", positive_number(self.sigma0, "sigma0"))
        variance_from_sigma(self.sigma0)
        supported_identity(self.underlying, self.currency)

    @property
    def v0(self) -> float:
        """Initial variance, sigma0 squared; not an additional independent input."""
        return self.sigma0 * self.sigma0


@dataclass(frozen=True, slots=True)
class Position:
    """Value convention: signed quantity * positive multiplier * per-unit price.

    Quantity is an integer number of contracts. Side is explicit and must agree
    with its sign, preventing a second sign inversion for short positions.
    """

    contract: OptionContract
    side: Side
    quantity: int
    multiplier: float

    def __post_init__(self) -> None:
        if not isinstance(self.contract, OptionContract):
            raise ContractValidationError("contract must be an OptionContract")
        if not isinstance(self.side, Side):
            raise ContractValidationError("side must be a Side")
        if type(self.quantity) is not int or self.quantity == 0:
            raise ContractValidationError("quantity must be a nonzero signed integer")
        finite_number(self.quantity, "quantity")
        if (self.side is Side.LONG and self.quantity < 0) or (
            self.side is Side.SHORT and self.quantity > 0
        ):
            raise ContractValidationError("quantity sign must agree with side: long > 0, short < 0")
        object.__setattr__(self, "multiplier", positive_number(self.multiplier, "multiplier"))

    def validate_for(self, market: MarketSnapshot) -> None:
        if not isinstance(market, MarketSnapshot):
            raise ContractValidationError("market must be a MarketSnapshot")
        if self.contract.underlying != market.underlying:
            raise ContractValidationError("contract and market underlying must match")
        if self.contract.currency != market.currency:
            raise ContractValidationError("contract and market currency must match")
        act365f(market.valuation_date, self.contract.expiry)


@dataclass(frozen=True, slots=True)
class HestonModelSpec:
    """Fixed Heston parameters, separate from each market's initial variance.

    kappa is annual mean reversion, theta is long-run annual variance, xi is
    volatility of variance and rho is correlation. The Feller condition is
    not a hard validity requirement for European Heston model inputs.
    The initial profile requires strictly positive kappa, theta and xi.
    """

    kappa: float
    theta: float
    xi: float
    rho: float

    def __post_init__(self) -> None:
        for field in ("kappa", "theta", "xi"):
            object.__setattr__(self, field, positive_number(getattr(self, field), field))
        object.__setattr__(self, "rho", finite_number(self.rho, "rho"))
        if not -1 <= self.rho <= 1:
            raise ContractValidationError("rho must be in [-1, 1]")


@dataclass(frozen=True, slots=True)
class StressScenario:
    """Explicit input units: +10 percent spot, +5 vol points, +100 rate bp.

    Those examples convert to relative spot change 0.10, absolute initial
    volatility change 0.05 and absolute annual rate change 0.01. Stress is
    instantaneous: transformations preserve the valuation date.
    """

    name: str
    spot_shock_pct: float = 0.0
    sigma0_shock_pp: float = 0.0
    rate_shock_bp: float = 0.0

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name.strip():
            raise ContractValidationError("scenario name must be a nonempty string")
        for field in ("spot_shock_pct", "sigma0_shock_pp", "rate_shock_bp"):
            object.__setattr__(self, field, finite_number(getattr(self, field), field))
        if self.spot_shock_pct <= -100:
            raise ContractValidationError("spot_shock_pct must be greater than -100")
        # Validate conversions at construction, before they can be consumed.
        _ = (self.spot_relative_change, self.sigma0_change, self.rate_change)

    @property
    def spot_relative_change(self) -> float:
        return convert_units(self.spot_shock_pct, 100.0, "spot_shock_pct")

    @property
    def sigma0_change(self) -> float:
        return convert_units(self.sigma0_shock_pp, 100.0, "sigma0_shock_pp")

    @property
    def rate_change(self) -> float:
        return convert_units(self.rate_shock_bp, 10_000.0, "rate_shock_bp")

    def validate_for(self, market: MarketSnapshot) -> None:
        """Reject financially invalid or non-finite shocked inputs; never clamp."""
        if not isinstance(market, MarketSnapshot):
            raise ContractValidationError("market must be a MarketSnapshot")
        positive_number(market.spot * (1.0 + self.spot_relative_change), "stressed spot")
        sigma0 = positive_number(market.sigma0 + self.sigma0_change, "stressed sigma0")
        variance_from_sigma(sigma0, "stressed sigma0")
        finite_number(market.rate + self.rate_change, "stressed rate")
