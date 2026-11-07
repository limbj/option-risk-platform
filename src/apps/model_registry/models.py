from django.db import models

from apps.common.models import ImmutableModel, OwnedSnapshot


class ModelVersion(OwnedSnapshot):
    """Published fixed Heston model specification."""


class ModelArtifact(ImmutableModel):
    name = models.CharField(max_length=120)
    manifest = models.JSONField()
    manifest_hash = models.CharField(max_length=64)
    relative_path = models.CharField(max_length=240)
