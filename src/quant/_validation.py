"""Small, strict validation primitives; no framework or pricing dependencies."""

from datetime import date
from math import isfinite

from quant.errors import ContractValidationError


def finite_number(value: object, field: str) -> float:
    """Accept JSON numbers, excluding bool, coercion from strings and overflow."""
    if type(value) not in (int, float):
        raise ContractValidationError(f"{field} must be a finite number, not a bool or string")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ContractValidationError(f"{field} must be representable as a finite float") from exc
    if not isfinite(number):
        raise ContractValidationError(f"{field} must be finite")
    return number


def positive_number(value: object, field: str) -> float:
    number = finite_number(value, field)
    if number <= 0:
        raise ContractValidationError(f"{field} must be positive")
    return number


def calendar_date(value: object, field: str) -> date:
    # datetime inherits date; accepting it would make time conventions ambiguous.
    if type(value) is not date:
        raise ContractValidationError(f"{field} must be a date without a time component")
    return value


def supported_identity(underlying: object, currency: object) -> None:
    if type(underlying) is not str or underlying != "SYNTH_INDEX":
        raise ContractValidationError("underlying must be SYNTH_INDEX in the initial profile")
    if type(currency) is not str or currency != "USD":
        raise ContractValidationError("currency must be USD in the initial profile")


def variance_from_sigma(sigma0: float, field: str = "sigma0") -> float:
    """Reject even positive volatilities whose variance over/underflows."""
    return positive_number(sigma0 * sigma0, f"{field} squared (initial variance)")


def convert_units(value: float, divisor: float, field: str) -> float:
    result = finite_number(value / divisor, field)
    if value != 0 and result == 0:
        raise ContractValidationError(f"{field} is too small to represent after unit conversion")
    return result
