import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import ImmutableModel, ImmutableQuerySet


class ValuationRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        COMPLETED = "COMPLETED"
        PARTIAL_ERROR = "PARTIAL_ERROR"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    inputs = models.ForeignKey("portfolios.InputVersion", on_delete=models.PROTECT)
    mode = models.CharField(
        max_length=12, choices=[("REFERENCE", "REFERENCE"), ("COMPARE", "COMPARE")]
    )
    artifact = models.ForeignKey(
        "model_registry.ModelArtifact", null=True, blank=True, on_delete=models.PROTECT
    )
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    provenance = models.JSONField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "idempotency_key"], name="unique_run_request")
        ]
        ordering = ["-created_at"]


def validate_chunk_insert(chunk, run):
    if (
        run.status != "QUEUED"
        or type(chunk.scenario_index) is not int
        or not 0 <= chunk.scenario_index < len(run.provenance["execution_scenarios"])
    ):
        raise ValidationError("New chunks require a queued run and an eligible scenario")


class ChunkQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        runs = {
            run.pk: run
            for run in ValuationRun.objects.filter(pk__in={chunk.run_id for chunk in objs})
        }
        for chunk in objs:
            if chunk.run_id not in runs:
                raise ValidationError("Chunk run does not exist")
            validate_chunk_insert(chunk, runs[chunk.run_id])
        return super().bulk_create(objs, **kwargs)


class RunChunk(models.Model):
    objects = ChunkQuerySet.as_manager()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(ValuationRun, related_name="chunks", on_delete=models.PROTECT)
    scenario_index = models.PositiveIntegerField()
    status = models.CharField(max_length=12, default="QUEUED")
    token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self._state.adding:
            validate_chunk_insert(self, ValuationRun.objects.get(pk=self.run_id))
        return super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "scenario_index"], name="unique_run_scenario")
        ]


def validate_result_insert(result, chunk):
    if (
        chunk.status != "RUNNING"
        or chunk.run.status != "RUNNING"
        or result.run_id != chunk.run_id
        or result.scenario_index != chunk.scenario_index
        or type(result.position_index) is not int
        or not 0 <= result.position_index < len(chunk.run.inputs.payload["positions"])
    ):
        raise ValidationError("Result must belong to an active chunk and an eligible position")


class ResultQuerySet(ImmutableQuerySet):
    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        chunks = {
            chunk.pk: chunk
            for chunk in RunChunk.objects.filter(
                pk__in={result.chunk_id for result in objs}
            ).select_related("run__inputs")
        }
        for result in objs:
            if result.chunk_id not in chunks:
                raise ValidationError("Result chunk does not exist")
            validate_result_insert(result, chunks[result.chunk_id])
        return super().bulk_create(objs, **kwargs)


class ValuationResult(ImmutableModel):
    objects = ResultQuerySet.as_manager()
    run = models.ForeignKey(ValuationRun, related_name="results", on_delete=models.PROTECT)
    chunk = models.ForeignKey(RunChunk, on_delete=models.PROTECT)
    scenario_index = models.PositiveIntegerField()
    position_index = models.PositiveIntegerField()
    status = models.CharField(max_length=12)
    reference_price = models.FloatField(null=True)
    reference_value = models.FloatField(null=True)
    sensitivities = models.JSONField(null=True)
    error = models.TextField(blank=True)
    ml_price = models.FloatField(null=True)
    ml_value = models.FloatField(null=True)
    ml_error = models.TextField(blank=True)
    timings = models.JSONField(default=dict)

    def save(self, *args, **kwargs):
        if self._state.adding:
            chunk = RunChunk.objects.select_related("run__inputs").get(pk=self.chunk_id)
            validate_result_insert(self, chunk)
        return super().save(*args, **kwargs)

    class Meta(ImmutableModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["run", "scenario_index", "position_index"], name="unique_result_cell"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="COMPLETED",
                        reference_price__isnull=False,
                        reference_value__isnull=False,
                        error="",
                    )
                    | models.Q(
                        status="FAILED", reference_price__isnull=True, reference_value__isnull=True
                    )
                ),
                name="result_success_or_failure",
            ),
        ]


class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chunk = models.ForeignKey(RunChunk, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True)
    token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
