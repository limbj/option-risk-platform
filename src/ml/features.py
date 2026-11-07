"""Documented, framework-independent features and supported-domain checks."""

from dataclasses import asdict
from math import isfinite, log

from quant.contracts import HestonModelSpec, MarketSnapshot, OptionContract
from quant.conventions import act365f

FEATURE_ORDER = ["log_moneyness", "maturity_years", "rate", "sigma0"]
DOMAIN = {
    "log_moneyness": [-0.4, 0.4],
    "maturity_years": [14 / 365, 2.0],
    "rate": [-0.03, 0.10],
    "sigma0": [0.05, 0.7],
}
DEFAULT_SPEC = HestonModelSpec(kappa=2.0, theta=0.04, xi=0.3, rho=-0.7)
HELDOUT_REGION = {
    "log_moneyness": [0.12, 0.22],
    "maturity_years": [0.5, 1.0],
    "sigma0": [0.22, 0.38],
}


class UnsupportedInput(ValueError):
    """A model or financial input is outside this artifact's supported contract."""


def features(contract: OptionContract, market: MarketSnapshot) -> list[float]:
    if contract.underlying != market.underlying or contract.currency != market.currency:
        raise UnsupportedInput("contract and market identities must match")
    return [
        log(market.spot) - log(contract.strike),
        act365f(market.valuation_date, contract.expiry),
        market.rate,
        market.sigma0,
    ]


def validate_features(values: list[float], domain: dict[str, list[float]]) -> None:
    for name, value in zip(FEATURE_ORDER, values, strict=True):
        low, high = domain[name]
        if not isfinite(value) or value < low - 1e-12 or value > high + 1e-12:
            raise UnsupportedInput(f"{name}={value:g} outside supported [{low:g}, {high:g}]")


def validate_spec(spec: HestonModelSpec, expected: dict[str, float]) -> None:
    if asdict(spec) != expected:
        raise UnsupportedInput("Heston model specification differs from artifact model_spec")


def in_heldout_region(values: list[float]) -> bool:
    record = dict(zip(FEATURE_ORDER, values, strict=True))
    return all(low <= record[key] <= high for key, (low, high) in HELDOUT_REGION.items())
