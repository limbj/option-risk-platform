from django.contrib import admin

from apps.common.admin import ReadOnlyAdmin
from apps.valuations.models import OutboxEvent, RunChunk, ValuationResult, ValuationRun

admin.site.register([ValuationRun, ValuationResult, RunChunk, OutboxEvent], ReadOnlyAdmin)
