"""QuantLib analytic Heston reference adapter with explicit date isolation."""

from collections import OrderedDict
from datetime import date
from threading import RLock

import QuantLib as ql

from quant.contracts import HestonModelSpec, MarketSnapshot, OptionContract, OptionType
from quant.errors import ContractValidationError, PricingError
from quant.pricing import checked_price, pricing_inputs

# All QuantLib settings and mutable engine access in this package use this lock.
# Workers still use separate processes: third-party QuantLib calls that ignore
# this lock cannot be protected by the adapter.
_QUANTLIB_LOCK = RLock()


def _ql_date(value: date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


class HestonPricer:
    """Reusable Gauss-Laguerre/Gatheral reference engine, q=0, ACT/365F.

    The immutable model specification is fixed for this instance. Within one
    valuation date, spot and rate quotes and the model's v0 parameter are updated
    while the engine is reused. A date change rebuilds date-anchored curves.
    Calls restore QuantLib settings on success and failure. Use process workers.
    """

    def __init__(self, spec: HestonModelSpec, integration_order: int = 144) -> None:
        if not isinstance(spec, HestonModelSpec):
            raise ContractValidationError("spec must be a HestonModelSpec")
        if type(integration_order) is not int or not 16 <= integration_order <= 192:
            raise ContractValidationError("integration_order must be an integer from 16 to 192")
        self._spec = spec
        self._integration_order = integration_order
        self._market_date: date | None = None
        self._v0: float | None = None
        self._options: OrderedDict[OptionContract, ql.VanillaOption] = OrderedDict()

    @property
    def spec(self) -> HestonModelSpec:
        return self._spec

    @property
    def integration_order(self) -> int:
        return self._integration_order

    def _prepare_market(self, market: MarketSnapshot) -> None:
        spec = self.spec
        if self._market_date != market.valuation_date:
            day_count = ql.Actual365Fixed()
            reference_date = _ql_date(market.valuation_date)
            self._spot_quote = ql.SimpleQuote(market.spot)
            self._rate_quote = ql.SimpleQuote(market.rate)
            risk_free = ql.YieldTermStructureHandle(
                ql.FlatForward(reference_date, ql.QuoteHandle(self._rate_quote), day_count)
            )
            dividends = ql.YieldTermStructureHandle(ql.FlatForward(reference_date, 0.0, day_count))
            process = ql.HestonProcess(
                risk_free,
                dividends,
                ql.QuoteHandle(self._spot_quote),
                market.v0,
                spec.kappa,
                spec.theta,
                spec.xi,
                spec.rho,
            )
            self._model = ql.HestonModel(process)
            self._engine = ql.AnalyticHestonEngine(self._model, self.integration_order)
            self._options.clear()
            self._market_date = market.valuation_date
            self._v0 = market.v0
        else:
            self._spot_quote.setValue(market.spot)
            self._rate_quote.setValue(market.rate)
            if self._v0 != market.v0:
                # QuantLib HestonModel parameter order is theta,kappa,sigma,rho,v0.
                self._model.setParams([spec.theta, spec.kappa, spec.xi, spec.rho, market.v0])
                self._v0 = market.v0

    def _option(self, contract: OptionContract) -> ql.VanillaOption:
        if contract in self._options:
            self._options.move_to_end(contract)
            return self._options[contract]
        payoff_type = ql.Option.Call if contract.option_type is OptionType.CALL else ql.Option.Put
        option = ql.VanillaOption(
            ql.PlainVanillaPayoff(payoff_type, contract.strike),
            ql.EuropeanExercise(_ql_date(contract.expiry)),
        )
        option.setPricingEngine(self._engine)
        self._options[contract] = option
        if len(self._options) > 256:
            self._options.popitem(last=False)
        return option

    def price(self, contract: OptionContract, market: MarketSnapshot) -> float:
        pricing_inputs(contract, market)
        try:
            with _QUANTLIB_LOCK, ql.SavedSettings():
                ql.Settings.instance().evaluationDate = _ql_date(market.valuation_date)
                self._prepare_market(market)
                value = float(self._option(contract).NPV())
        except (RuntimeError, OverflowError) as exc:
            raise PricingError(f"QuantLib AnalyticHestonEngine failed: {exc}") from exc
        return checked_price(value, contract, market)
