"""Instantaneous, deterministic market shocks with explicit input units."""

from dataclasses import replace

from quant.contracts import MarketSnapshot, StressScenario
from quant.errors import ContractValidationError


def apply_stress(market: MarketSnapshot, scenario: StressScenario) -> MarketSnapshot:
    """Return a new snapshot, preserving date, currency and underlying.

    sigma0 changes absolutely, so derived v0=(sigma0+delta_sigma0)**2. The
    function does not change the Heston model specification or residual maturity.
    """
    if not isinstance(scenario, StressScenario):
        raise ContractValidationError("scenario must be a StressScenario")
    scenario.validate_for(market)
    return replace(
        market,
        spot=market.spot * (1.0 + scenario.spot_relative_change),
        sigma0=market.sigma0 + scenario.sigma0_change,
        rate=market.rate + scenario.rate_change,
    )
