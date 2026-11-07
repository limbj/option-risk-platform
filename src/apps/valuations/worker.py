"""Fenced, leased chunks: calculations run entirely outside DB transactions."""

import hashlib
import math
import time
import uuid
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.valuations.models import OutboxEvent, RunChunk, ValuationResult, ValuationRun
from apps.valuations.services import code_version, software_versions, verify_run_inputs
from quant.contracts import StressScenario

TERMINAL = {"COMPLETED", "PARTIAL_ERROR", "FAILED"}


def _claim(chunk_id):
    run_id = RunChunk.objects.values_list("run_id", flat=True).get(pk=chunk_id)
    with transaction.atomic():
        run = ValuationRun.objects.select_for_update().get(pk=run_id)
        chunk = RunChunk.objects.select_for_update().get(pk=chunk_id)
        now = timezone.now()
        if run.status in TERMINAL or chunk.status in {"COMPLETED", "FAILED"}:
            return None
        if chunk.status == "RUNNING" and chunk.lease_until and chunk.lease_until > now:
            return None
        if chunk.attempts >= settings.CHUNK_MAX_ATTEMPTS:
            _persist_locked(run, chunk, _failed_cells(run, "Worker attempts exhausted"))
            return None
        chunk.status = "RUNNING"
        chunk.token = uuid.uuid4()
        chunk.attempts += 1
        chunk.lease_until = now + timedelta(seconds=settings.CHUNK_LEASE_SECONDS)
        chunk.save(update_fields=["status", "token", "attempts", "lease_until"])
        if run.status == "QUEUED":
            run.status = "RUNNING"
            run.started_at = now
            run.save(update_fields=["status", "started_at"])
        return chunk.token


def _artifact(run):
    if run.artifact is None:
        return None
    from ml.inference import load_artifact

    root = Path(settings.ARTIFACT_ROOT).resolve()
    path = (root / run.artifact.relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Artifact path is outside the configured artifact root")
    manifest_hash = hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()
    if manifest_hash != run.provenance["artifact_manifest_hash"]:
        raise ValueError("Pinned artifact manifest hash mismatch")
    return load_artifact(path)


def _calculate(chunk):
    from quant.heston import HestonPricer
    from quant.risk import sensitivities
    from quant.stress import apply_stress

    run = chunk.run
    inputs = verify_run_inputs(run)
    if code_version() != run.provenance["code_version"]:
        raise ValueError("Worker source differs from the pinned run code version")
    if software_versions() != run.provenance["software_versions"]:
        raise ValueError("Worker software differs from the pinned run software versions")
    scenario = StressScenario(**run.provenance["execution_scenarios"][chunk.scenario_index])
    market = apply_stress(inputs.market, scenario)
    pricer = HestonPricer(inputs.model, integration_order=run.provenance["integration_order"])
    surrogate, artifact_error = None, ""
    if run.mode == "COMPARE":
        try:
            surrogate = _artifact(run)
        except Exception as exc:
            artifact_error = f"{type(exc).__name__}: {exc}"[:2000]
    cells = []
    for index, position in enumerate(inputs.positions):
        cell = {
            "position_index": index,
            "status": "FAILED",
            "reference_price": None,
            "reference_value": None,
            "sensitivities": None,
            "error": "",
            "ml_price": None,
            "ml_value": None,
            "ml_error": "",
            "timings": {},
        }
        started = time.perf_counter()
        try:
            price = float(pricer.price(position.contract, market))
            value = price * position.quantity * position.multiplier
            if not math.isfinite(price) or price < 0 or not math.isfinite(value):
                raise ValueError("Reference output is not a finite, valid price/value")
            cell.update(status="COMPLETED", reference_price=price, reference_value=value)
            if chunk.scenario_index == run.provenance["base_scenario_index"]:
                cell["sensitivities"] = asdict(
                    sensitivities(
                        position.contract,
                        market,
                        pricer.price,
                        spot_relative_bump=run.provenance["sensitivity_settings"][
                            "spot_relative_bump"
                        ],
                        sigma0_bump=run.provenance["sensitivity_settings"]["sigma0_bump"],
                    )
                )
        except Exception as exc:
            # A failed sensitivity also makes this reference cell incomplete.
            cell.update(
                status="FAILED",
                reference_price=None,
                reference_value=None,
                sensitivities=None,
                error=f"{type(exc).__name__}: {exc}"[:2000],
            )
        cell["timings"]["reference_seconds"] = time.perf_counter() - started
        if run.mode == "COMPARE":
            started = time.perf_counter()
            try:
                if artifact_error:
                    raise ValueError(artifact_error)
                ml_price = float(surrogate.price(position.contract, market, inputs.model))
                ml_value = ml_price * position.quantity * position.multiplier
                if not math.isfinite(ml_price) or ml_price < 0 or not math.isfinite(ml_value):
                    raise ValueError("ML output is not a finite, valid price/value")
                cell.update(ml_price=ml_price, ml_value=ml_value)
            except Exception as exc:
                cell["ml_error"] = f"{type(exc).__name__}: {exc}"[:2000]
            cell["timings"]["ml_seconds"] = time.perf_counter() - started
        cells.append(cell)
    return cells


def _failed_cells(run, message):
    return [
        {"position_index": index, "status": "FAILED", "error": message[:2000]}
        for index in range(len(run.inputs.payload["positions"]))
    ]


def _persist_locked(run, chunk, cells):
    expected = len(run.inputs.payload["positions"])
    if len(cells) != expected or {cell["position_index"] for cell in cells} != set(range(expected)):
        raise ValueError("A chunk must finalize every required position exactly once")
    ValuationResult.objects.bulk_create(
        [
            ValuationResult(run=run, chunk=chunk, scenario_index=chunk.scenario_index, **cell)
            for cell in cells
        ]
    )
    chunk.status = "FAILED" if any(cell["status"] == "FAILED" for cell in cells) else "COMPLETED"
    chunk.lease_until = None
    chunk.save(update_fields=["status", "lease_until"])
    if not run.chunks.exclude(status__in=["COMPLETED", "FAILED"]).exists():
        successful = run.results.filter(status="COMPLETED").count()
        failed = run.results.filter(status="FAILED").count()
        run.status = (
            "PARTIAL_ERROR" if successful and failed else ("FAILED" if failed else "COMPLETED")
        )
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])


def _finalize(chunk_id, token, cells):
    run_id = RunChunk.objects.values_list("run_id", flat=True).get(pk=chunk_id)
    with transaction.atomic():
        run = ValuationRun.objects.select_for_update().select_related("inputs").get(pk=run_id)
        chunk = RunChunk.objects.select_for_update().get(pk=chunk_id)
        if (
            chunk.status != "RUNNING"
            or chunk.token != token
            or not chunk.lease_until
            or chunk.lease_until <= timezone.now()
            or run.status in TERMINAL
        ):
            return False
        _persist_locked(run, chunk, cells)
        return True


def execute_chunk(chunk_id):
    token = _claim(chunk_id)
    if token is None:
        return False
    chunk = RunChunk.objects.select_related("run__inputs", "run__artifact").get(pk=chunk_id)
    try:
        cells = _calculate(chunk)
    except Exception as exc:
        cells = _failed_cells(chunk.run, f"{type(exc).__name__}: {exc}")
    return _finalize(chunk_id, token, cells)


def dispatch_pending(publish=None, limit=100):
    if publish is None:
        from apps.valuations.tasks import calculate_chunk

        def publish(chunk_id):
            return calculate_chunk.delay(str(chunk_id))

    sent = 0
    for _ in range(limit):
        now = timezone.now()
        with transaction.atomic():
            query = (
                OutboxEvent.objects.filter(published_at__isnull=True)
                .filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
                .order_by("created_at")
            )
            event = query.select_for_update().first()
            if event is None:
                break
            token = uuid.uuid4()
            event.token, event.lease_until = token, now + timedelta(seconds=30)
            event.attempts += 1
            event.save(update_fields=["token", "lease_until", "attempts"])
            event_id, chunk_id = event.pk, event.chunk_id
        # Publishing is deliberately outside the transaction. A lost ACK may publish twice.
        try:
            publish(str(chunk_id))
        except Exception as exc:
            OutboxEvent.objects.filter(pk=event_id, token=token).update(
                lease_until=None, last_error=f"{type(exc).__name__}: {exc}"[:2000]
            )
            break
        updated = OutboxEvent.objects.filter(pk=event_id, token=token).update(
            published_at=timezone.now(), lease_until=None, last_error=""
        )
        sent += updated
    return sent


def recover_work():
    """Requeue abandoned leases and messages lost after publication; fence old workers."""
    recovered = 0
    cutoff = timezone.now() - timedelta(seconds=settings.QUEUE_RECOVERY_SECONDS)
    ids = list(
        RunChunk.objects.filter(
            Q(status="RUNNING", lease_until__lte=timezone.now())
            | Q(status="QUEUED", run__created_at__lte=cutoff)
        ).values_list("id", flat=True)
    )
    for chunk_id in ids:
        run_id = RunChunk.objects.values_list("run_id", flat=True).get(pk=chunk_id)
        with transaction.atomic():
            run = ValuationRun.objects.select_for_update().select_related("inputs").get(pk=run_id)
            chunk = RunChunk.objects.select_for_update().get(pk=chunk_id)
            if run.status in TERMINAL or chunk.status in {"COMPLETED", "FAILED"}:
                continue
            abandoned = chunk.status == "RUNNING"
            if abandoned:
                if chunk.lease_until and chunk.lease_until > timezone.now():
                    continue
                if chunk.attempts >= settings.CHUNK_MAX_ATTEMPTS:
                    _persist_locked(
                        run, chunk, _failed_cells(run, "Worker lease expired; attempts exhausted")
                    )
                    recovered += 1
                    continue
                chunk.status, chunk.token, chunk.lease_until = "QUEUED", None, None
                chunk.last_error = "Previous worker lease expired"
                chunk.save(update_fields=["status", "token", "lease_until", "last_error"])
            if not OutboxEvent.objects.filter(chunk=chunk, published_at__isnull=True).exists():
                recent = OutboxEvent.objects.filter(chunk=chunk, published_at__gte=cutoff).exists()
                if abandoned or not recent:
                    OutboxEvent.objects.create(chunk=chunk)
                    if not abandoned:
                        recovered += 1
            if abandoned:
                recovered += 1
    return recovered
