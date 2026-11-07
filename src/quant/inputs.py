"""Strict JSON-shaped input parsing, reusable by future HTTP and CSV adapters."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from re import fullmatch
from typing import Any

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

MAX_POSITIONS = 100
MAX_SCENARIOS = 100


@dataclass(frozen=True, slots=True)
class InputBundle:
    """A deeply immutable, validated set of inputs, not a persisted version."""

    market: MarketSnapshot
    model: HestonModelSpec
    positions: tuple[Position, ...]
    scenarios: tuple[StressScenario, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.market, MarketSnapshot):
            raise ContractValidationError("market must be a MarketSnapshot")
        if not isinstance(self.model, HestonModelSpec):
            raise ContractValidationError("model must be a HestonModelSpec")
        _tuple_items(self.positions, Position, "positions", MAX_POSITIONS)
        _tuple_items(self.scenarios, StressScenario, "scenarios", MAX_SCENARIOS)
        for position in self.positions:
            position.validate_for(self.market)
        names: set[str] = set()
        for scenario in self.scenarios:
            if scenario.name in names:
                raise ContractValidationError("scenario names must be unique")
            names.add(scenario.name)
            scenario.validate_for(self.market)


def _tuple_items(values: object, item_type: type, field: str, limit: int) -> None:
    if type(values) is not tuple:
        raise ContractValidationError(f"{field} must be an immutable tuple")
    if not 1 <= len(values) <= limit:
        raise ContractValidationError(f"{field} must contain between 1 and {limit} items")
    if any(not isinstance(value, item_type) for value in values):
        raise ContractValidationError(f"{field} must contain {item_type.__name__} objects")


def _object(
    value: object, field: str, required: set[str], optional: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field} must be an object")
    if any(type(key) is not str for key in value):
        raise ContractValidationError(f"{field} keys must be strings")
    keys = set(value)
    missing = required - keys
    unknown = keys - required - (optional or set())
    if missing:
        raise ContractValidationError(f"{field} is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ContractValidationError(f"{field} has unknown fields: {', '.join(sorted(unknown))}")
    return dict(value)


def _date(value: object, field: str) -> date:
    if type(value) is not str or fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ContractValidationError(f"{field} must use ISO date format YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ContractValidationError(f"{field} must be a valid calendar date") from exc


def _enum(value: object, enum_type: type[OptionType] | type[Side], field: str):
    if type(value) is not str:
        raise ContractValidationError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        choices = ", ".join(item.value for item in enum_type)
        raise ContractValidationError(f"{field} must be one of: {choices}") from exc


def _array(value: object, field: str, limit: int) -> list[Any]:
    if type(value) is not list:
        raise ContractValidationError(f"{field} must be a JSON array")
    if not 1 <= len(value) <= limit:
        raise ContractValidationError(f"{field} must contain between 1 and {limit} items")
    return value


def _position(value: object, index: int) -> Position:
    field = f"positions[{index}]"
    data = _object(value, field, {"contract", "side", "quantity", "multiplier"})
    contract = _object(
        data["contract"],
        f"{field}.contract",
        {"option_type", "strike", "expiry"},
        {"underlying", "currency"},
    )
    contract["option_type"] = _enum(
        contract["option_type"], OptionType, f"{field}.contract.option_type"
    )
    contract["expiry"] = _date(contract["expiry"], f"{field}.contract.expiry")
    data["contract"] = OptionContract(**contract)
    data["side"] = _enum(data["side"], Side, f"{field}.side")
    return Position(**data)


def parse_inputs(payload: object) -> InputBundle:
    """Parse a JSON object without silently coercing units, signs, or dates.

    Only sigma0 is accepted for initial volatility, not a simultaneous v0.
    Unknown fields fail so misspelled unit names cannot silently default to 0.
    This parses objects produced by a JSON decoder; file I/O stays with callers.
    """
    data = _object(payload, "inputs", {"market", "model", "positions", "scenarios"})
    market = _object(
        data["market"],
        "market",
        {"valuation_date", "spot", "rate", "sigma0"},
        {"underlying", "currency"},
    )
    market["valuation_date"] = _date(market["valuation_date"], "market.valuation_date")
    model = _object(data["model"], "model", {"kappa", "theta", "xi", "rho"})
    positions = _array(data["positions"], "positions", MAX_POSITIONS)
    scenarios = _array(data["scenarios"], "scenarios", MAX_SCENARIOS)
    return InputBundle(
        market=MarketSnapshot(**market),
        model=HestonModelSpec(**model),
        positions=tuple(_position(value, index) for index, value in enumerate(positions)),
        scenarios=tuple(
            StressScenario(
                **_object(
                    value,
                    f"scenarios[{index}]",
                    {"name"},
                    {"spot_shock_pct", "sigma0_shock_pp", "rate_shock_bp"},
                )
            )
            for index, value in enumerate(scenarios)
        ),
    )
