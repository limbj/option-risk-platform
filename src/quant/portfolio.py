"""Signed values and aggregation that never invents incomplete totals."""

from collections.abc import Iterable
from dataclasses import dataclass
from math import fsum, isfinite

from quant._validation import finite_number
from quant.contracts import Position
from quant.errors import ContractValidationError, PricingError


def position_value(position: Position, per_unit_price: float) -> float:
    if not isinstance(position, Position):
        raise ContractValidationError("position must be a Position")
    price = finite_number(per_unit_price, "per_unit_price")
    if price < 0:
        raise PricingError("per_unit_price must not be negative")
    value = position.quantity * position.multiplier * price
    if not isfinite(value):
        raise PricingError("position value overflowed")
    return value


@dataclass(frozen=True, slots=True)
class PositionValuation:
    position_id: str
    value: float | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if type(self.position_id) is not str or not self.position_id.strip():
            raise ContractValidationError("position_id must be a nonempty string")
        if (self.value is None) == (self.error is None):
            raise ContractValidationError("a cell must contain either value or error")
        if self.value is not None:
            object.__setattr__(self, "value", finite_number(self.value, "value"))
        elif type(self.error) is not str or not self.error.strip():
            raise ContractValidationError("error must be a nonempty reason")


@dataclass(frozen=True, slots=True)
class PortfolioTotal:
    total: float | None
    source: str
    required_position_ids: tuple[str, ...]
    completed_count: int
    errors: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.source) is not str or not self.source.strip():
            raise ContractValidationError("source must identify the model/engine/version")
        if (
            type(self.required_position_ids) is not tuple
            or not self.required_position_ids
            or any(type(item) is not str or not item.strip() for item in self.required_position_ids)
            or len(set(self.required_position_ids)) != len(self.required_position_ids)
        ):
            raise ContractValidationError("required position IDs must be a nonempty unique tuple")
        if type(self.completed_count) is not int or not (
            0 <= self.completed_count <= len(self.required_position_ids)
        ):
            raise ContractValidationError("completed_count is outside the required position count")
        if type(self.errors) is not tuple or any(
            type(error) is not str or not error.strip() for error in self.errors
        ):
            raise ContractValidationError("errors must be an immutable tuple of failure reasons")
        if self.total is not None:
            object.__setattr__(self, "total", finite_number(self.total, "total"))
            if self.completed_count != len(self.required_position_ids) or self.errors:
                raise ContractValidationError("a total requires every position to complete")
        elif self.completed_count == len(self.required_position_ids) or not self.errors:
            raise ContractValidationError("an incomplete total requires missing/failed results")

    @property
    def complete(self) -> bool:
        return self.total is not None


def aggregate_portfolio(
    cells: Iterable[PositionValuation],
    required_position_ids: Iterable[str],
    *,
    source: str,
) -> PortfolioTotal:
    """A missing or failed required cell makes the total unavailable.

    source is the same explicit model/engine/version label for all cells; the
    application must pin and verify provenance before constructing this set.
    """
    required = tuple(required_position_ids)
    if not required or any(type(item) is not str or not item.strip() for item in required):
        raise ContractValidationError("required position IDs must be nonempty strings")
    if len(set(required)) != len(required):
        raise ContractValidationError("required position IDs must be unique")
    if type(source) is not str or not source.strip():
        raise ContractValidationError("source must identify the model/engine/version")
    found: dict[str, PositionValuation] = {}
    for cell in cells:
        if not isinstance(cell, PositionValuation):
            raise ContractValidationError("cells must contain PositionValuation objects")
        if cell.position_id not in required or cell.position_id in found:
            raise ContractValidationError("unexpected or duplicate position result")
        found[cell.position_id] = cell
    errors = tuple(
        f"{position_id}: {found[position_id].error if position_id in found else 'missing result'}"
        for position_id in required
        if position_id not in found or found[position_id].error is not None
    )
    values = [cell.value for cell in found.values() if cell.value is not None]
    total = None
    if not errors:
        try:
            total = fsum(values)
        except OverflowError as exc:
            raise PricingError("portfolio total overflowed") from exc
        if not isfinite(total):
            raise PricingError("portfolio total is not finite")
    return PortfolioTotal(total, source, required, len(values), errors)


def stress_pnl(base: PortfolioTotal, stressed: PortfolioTotal) -> float | None:
    """Only complete, like-for-like model and position sets have stress P&L."""
    if not isinstance(base, PortfolioTotal) or not isinstance(stressed, PortfolioTotal):
        raise ContractValidationError("P&L requires PortfolioTotal objects")
    if base.source != stressed.source:
        raise ContractValidationError("base and stressed model/engine/version must match")
    if set(base.required_position_ids) != set(stressed.required_position_ids):
        raise ContractValidationError("base and stressed position sets must match")
    if not base.complete or not stressed.complete:
        return None
    value = stressed.total - base.total
    if not isfinite(value):
        raise PricingError("stress P&L overflowed")
    return value
