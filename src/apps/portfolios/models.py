from django.db import models

from apps.common.models import OwnedSnapshot


class PortfolioVersion(OwnedSnapshot):
    """Published positions; signed quantities and multipliers remain explicit."""


class InputVersion(OwnedSnapshot):
    name = models.CharField(max_length=120)
    portfolio = models.ForeignKey(PortfolioVersion, on_delete=models.PROTECT)
    market = models.ForeignKey("marketdata.MarketSnapshot", on_delete=models.PROTECT)
    scenarios = models.ForeignKey("marketdata.ScenarioSetVersion", on_delete=models.PROTECT)
    model = models.ForeignKey("model_registry.ModelVersion", on_delete=models.PROTECT)
