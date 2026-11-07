from datetime import date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from quant.conventions import act365f
from quant.errors import ContractValidationError


def test_act365f_uses_actual_days_even_in_a_leap_year():
    assert act365f(date(2024, 1, 1), date(2025, 1, 1)) == 366 / 365
    assert act365f(date(2024, 2, 28), date(2024, 3, 1)) == 2 / 365
    assert act365f(date(2025, 1, 1), date(2026, 1, 1)) == 1.0


@pytest.mark.parametrize("expiry", [date(2026, 1, 1), date(2025, 12, 31)])
def test_maturity_must_be_strictly_after_valuation_date(expiry):
    with pytest.raises(ContractValidationError):
        act365f(date(2026, 1, 1), expiry)


@pytest.mark.parametrize("invalid", ["2026-01-01", datetime(2026, 1, 1), None, 1])
def test_calendar_dates_are_required_without_silent_time_truncation(invalid):
    with pytest.raises(ContractValidationError):
        act365f(invalid, date(2027, 1, 1))
    with pytest.raises(ContractValidationError):
        act365f(date(2025, 1, 1), invalid)


@given(
    valuation_date=st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 1, 1)),
    days=st.integers(min_value=1, max_value=3650),
)
def test_act365f_counts_calendar_days_with_a_fixed_denominator(valuation_date, days):
    assert act365f(valuation_date, valuation_date + timedelta(days=days)) == days / 365
