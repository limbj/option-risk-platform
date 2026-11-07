"""The initial European-option profile uses calendar dates and ACT/365F."""

from datetime import date

from quant._validation import calendar_date
from quant.errors import ContractValidationError


def act365f(valuation_date: date, expiry: date) -> float:
    """Actual calendar days / 365, with a strictly positive residual maturity.

    Leap days count as actual days; the denominator remains 365. Expiry on the
    valuation date is not eligible for this initial pre-expiry pricing profile.
    """
    calendar_date(valuation_date, "valuation_date")
    calendar_date(expiry, "expiry")
    days = (expiry - valuation_date).days
    if days <= 0:
        raise ContractValidationError("expiry must be strictly after valuation_date")
    return days / 365.0
