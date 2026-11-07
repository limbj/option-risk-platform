import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ImmutableQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Published records cannot be upserted.")
        return super().bulk_create(objs, **kwargs)

    def update(self, **kwargs):
        raise ValidationError("Published records are immutable; create a new version.")

    def delete(self):
        raise ValidationError("Published records cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Published records are immutable; create a new version.")


class ImmutableModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True
        base_manager_name = "objects"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Published records are immutable; create a new version.")
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Published records cannot be deleted.")


class OwnedSnapshot(ImmutableModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    payload = models.JSONField()
    hash = models.CharField(max_length=64)

    class Meta(ImmutableModel.Meta):
        abstract = True
