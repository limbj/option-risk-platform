from django.contrib import admin

from apps.common.admin import ReadOnlyAdmin
from apps.model_registry.models import ModelArtifact, ModelVersion

admin.site.register([ModelArtifact, ModelVersion], ReadOnlyAdmin)
