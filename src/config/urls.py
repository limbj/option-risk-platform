"""Initial routes. Resource APIs are introduced with persistence in stage 4."""

from django.contrib import admin
from django.urls import path

from apps.accounts import views as account_views
from apps.valuations import views as valuation_views
from config.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/session/", account_views.session_view),
    path("api/login/", account_views.login_view),
    path("api/logout/", account_views.logout_view),
    path("api/sample/", valuation_views.sample),
    path("api/inputs/", valuation_views.inputs),
    path("api/inputs/<uuid:input_id>/", valuation_views.input_detail),
    path("api/runs/", valuation_views.runs),
    path("api/runs/<uuid:run_id>/", valuation_views.run_detail),
    path("api/runs/<uuid:run_id>/retry/", valuation_views.retry),
    path("api/runs/<uuid:run_id>/export/", valuation_views.export),
    path("api/models/", valuation_views.models),
]
