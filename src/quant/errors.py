"""Errors shared by the framework-independent financial input boundary."""


class ContractValidationError(ValueError):
    """An input cannot be represented by the supported financial contract."""


class PricingError(ValueError):
    """A calculation failed or produced an invalid/non-finite financial result."""
