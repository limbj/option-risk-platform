"""Independent regressions for provenance, terminal sealing and lease fencing."""

import copy
import importlib.metadata
import json
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Event

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.utils import timezone

from apps.valuations import worker
from apps.valuations.models import OutboxEvent, RunChunk, ValuationResult, ValuationRun
from apps.valuations.services import create_inputs, create_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def review_run(django_user_model):
    owner = django_user_model.objects.create_user(username="independent-review-owner")
    payload = json.loads((settings.BASE_DIR / "examples" / "stage1_inputs.json").read_text())
    inputs = create_inputs(owner, "Independent review", payload)
    return create_run(owner, inputs, "REFERENCE", "independent-review")[0]


def _cells(chunk):
    return [
        {
            "position_index": index,
            "status": "COMPLETED",
            "reference_price": 10.0,
            "reference_value": 10.0 * position["quantity"] * position["multiplier"],
            "error": "",
        }
        for index, position in enumerate(chunk.run.inputs.payload["positions"])
    ]


def _finish(run, monkeypatch):
    monkeypatch.setattr(worker, "_calculate", _cells)
    for chunk in run.chunks.all():
        assert worker.execute_chunk(chunk.pk)
    run.refresh_from_db()
    assert run.status == "COMPLETED"


def test_worker_rejects_a_different_pinned_runtime(review_run, monkeypatch):
    actual_version = importlib.metadata.version

    def different_quantlib(package):
        return "incompatible-test-version" if package == "QuantLib" else actual_version(package)

    monkeypatch.setattr(importlib.metadata, "version", different_quantlib)
    monkeypatch.setattr(worker, "code_version", lambda: review_run.provenance["code_version"])
    chunk = review_run.chunks.first()
    assert worker.execute_chunk(chunk.pk)
    results = list(review_run.results.all())
    assert results and all(result.status == "FAILED" for result in results)
    assert all("software" in result.error.lower() for result in results)
    assert all(result.reference_price is None for result in results)


@pytest.mark.parametrize(
    "mismatch", ["input_hash", "component_hash", "version_id", "scenarios", "base_index"]
)
def test_worker_checks_run_pins_against_snapshot_records(review_run, mismatch, monkeypatch):
    # Fault-inject a bad pin at initial insertion. No UPDATE bypass is needed,
    # and each underlying immutable snapshot remains individually valid.
    provenance = copy.deepcopy(review_run.provenance)
    if mismatch == "input_hash":
        provenance["input_hash"] = "0" * 64
    elif mismatch == "component_hash":
        provenance["component_hashes"]["market"] = "0" * 64
    elif mismatch == "version_id":
        provenance["version_ids"]["market"] = str(uuid.uuid4())
    elif mismatch == "scenarios":
        provenance["execution_scenarios"][0]["spot_shock_pct"] = 5.0
    else:
        provenance["base_scenario_index"] = 1
    invalid = ValuationRun.objects.create(
        owner=review_run.owner,
        inputs=review_run.inputs,
        mode=review_run.mode,
        idempotency_key=f"bad-pin-{mismatch}",
        request_hash=review_run.request_hash,
        provenance=provenance,
    )
    chunk = RunChunk.objects.create(run=invalid, scenario_index=0)
    monkeypatch.setattr(worker, "code_version", lambda: provenance["code_version"])
    assert worker.execute_chunk(chunk.pk)
    results = list(invalid.results.all())
    assert results and all(result.status == "FAILED" for result in results)
    assert all(result.reference_price is None and result.error for result in results)


def test_completed_result_set_rejects_an_extra_row(review_run, monkeypatch):
    _finish(review_run, monkeypatch)
    chunk = review_run.chunks.first()
    previous_count = review_run.results.count()
    with pytest.raises((ValidationError, DatabaseError)), transaction.atomic():
        ValuationResult.objects.create(
            run=review_run,
            chunk=chunk,
            scenario_index=chunk.scenario_index,
            position_index=999,
            status="COMPLETED",
            reference_price=10,
            reference_value=10,
        )
    assert review_run.results.count() == previous_count


def test_result_cannot_claim_a_chunk_from_a_different_run(review_run):
    another, _ = create_run(review_run.owner, review_run.inputs, "REFERENCE", "another-run")
    own_chunk, other_chunk = review_run.chunks.first(), another.chunks.first()
    assert worker._claim(own_chunk.pk)
    assert worker._claim(other_chunk.pk)
    with pytest.raises((ValidationError, DatabaseError)), transaction.atomic():
        ValuationResult.objects.create(
            run=review_run,
            chunk=other_chunk,
            scenario_index=other_chunk.scenario_index,
            position_index=0,
            status="COMPLETED",
            reference_price=10,
            reference_value=10,
        )
    assert review_run.results.count() == another.results.count() == 0


def test_completed_run_rejects_an_extra_chunk(review_run, monkeypatch):
    _finish(review_run, monkeypatch)
    previous_count = review_run.chunks.count()
    with pytest.raises((ValidationError, DatabaseError)), transaction.atomic():
        RunChunk.objects.create(run=review_run, scenario_index=999)
    assert review_run.chunks.count() == previous_count


def test_postgres_raw_insert_cannot_append_to_completed_results(review_run, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL trigger, not ORM-only validation")
    _finish(review_run, monkeypatch)
    existing = review_run.results.first()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO valuations_valuationresult
              (id, created_at, run_id, chunk_id, scenario_index, position_index, status,
               reference_price, reference_value, sensitivities, error, ml_price, ml_value,
               ml_error, timings)
            SELECT %s, created_at, run_id, chunk_id, scenario_index, 999, status,
                   reference_price, reference_value, sensitivities, error, ml_price, ml_value,
                   ml_error, timings
            FROM valuations_valuationresult WHERE id = %s
            """,
            [uuid.uuid4(), existing.pk],
        )


def test_expired_current_attempt_is_fenced_even_before_recovery(review_run):
    chunk = review_run.chunks.select_related("run__inputs").first()
    token = worker._claim(chunk.pk)
    RunChunk.objects.filter(pk=chunk.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    assert worker._finalize(chunk.pk, token, _cells(chunk)) is False
    assert review_run.results.count() == 0


@pytest.mark.django_db(transaction=True)
def test_postgres_result_insert_serializes_with_run_sealing(review_run):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL transaction isolation and real row locks")
    chunk = review_run.chunks.first()
    assert worker._claim(chunk.pk)
    attempted = Event()

    def insert_while_parent_is_sealing():
        close_old_connections()
        try:
            attempted.set()
            ValuationResult.objects.create(
                run_id=review_run.pk,
                chunk_id=chunk.pk,
                scenario_index=chunk.scenario_index,
                position_index=0,
                status="COMPLETED",
                reference_price=10,
                reference_value=10,
            )
            return "inserted"
        except (ValidationError, DatabaseError):
            return "rejected"
        finally:
            connections.close_all()

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with transaction.atomic():
            sealing = ValuationRun.objects.select_for_update().get(pk=review_run.pk)
            sealing.status = "COMPLETED"
            sealing.completed_at = timezone.now()
            sealing.save(update_fields=["status", "completed_at"])
            future = pool.submit(insert_while_parent_is_sealing)
            assert attempted.wait(timeout=5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.2)
        assert future.result(timeout=10) == "rejected"
    finally:
        pool.shutdown(wait=True)
    assert review_run.results.count() == 0


def test_stale_outbox_dispatcher_cannot_acknowledge_a_newer_lease(review_run):
    stolen = []

    def steal_lease_during_publish(chunk_id):
        event = OutboxEvent.objects.get(chunk_id=chunk_id)
        stolen.append(event.pk)
        OutboxEvent.objects.filter(pk=event.pk).update(
            token=uuid.uuid4(), lease_until=timezone.now() + timedelta(seconds=30)
        )

    assert worker.dispatch_pending(steal_lease_during_publish, limit=1) == 0
    event = OutboxEvent.objects.get(pk=stolen[0])
    assert event.published_at is None
    assert event.lease_until > timezone.now()
