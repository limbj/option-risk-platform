from django.contrib import admin

from apps.common.admin import ReadOnlyAdmin
from apps.marketdata.models import MarketSnapshot, ScenarioSetVersion

admin.site.register([MarketSnapshot, ScenarioSetVersion], ReadOnlyAdmin)
