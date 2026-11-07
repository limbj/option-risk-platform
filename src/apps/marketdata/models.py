from apps.common.models import OwnedSnapshot


class MarketSnapshot(OwnedSnapshot):
    """Published valuation date and flat market inputs."""


class ScenarioSetVersion(OwnedSnapshot):
    """Published deterministic instantaneous stress definitions."""
