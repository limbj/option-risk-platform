from django.contrib import admin

from apps.common.admin import ReadOnlyAdmin
from apps.portfolios.models import InputVersion, PortfolioVersion

admin.site.register([InputVersion, PortfolioVersion], ReadOnlyAdmin)
