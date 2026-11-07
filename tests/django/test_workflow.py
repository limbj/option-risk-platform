import copy
import json
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.marketdata.models import MarketSnapshot
from apps.model_registry.models import ModelArtifact
from apps.portfolios.models import InputVersion, PortfolioVersion
from apps.valuations import worker
from apps.valuations.models import OutboxEvent, RunChunk, ValuationResult, ValuationRun
from apps.valuations.reporting import run_document
from apps.valuations.services import IdempotencyConflict, create_inputs, create_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def payload():
    return json.loads((settings.BASE_DIR / "examples" / "stage1_inputs.json").read_text())


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(username="owner", password="test-secret-password")


@pytest.fixture
def inputs(owner, payload):
    return create_inputs(owner, "Synthetic fixture", payload)


@pytest.fixture
def run(owner, inputs):
    return create_run(owner, inputs, "REFERENCE", "request-1")[0]


def cells(chunk, failed_positions=()):
    return [
        {
            "position_index": index,
            "status": "FAILED" if index in failed_positions else "COMPLETED",
            "reference_price": None if index in failed_positions else 10.0,
            "reference_value": None
            if index in failed_positions
            else 10.0 * position["quantity"] * position["multiplier"],
            "error": "pricing failure" if index in failed_positions else "",
        }
        for index, position in enumerate(chunk.run.inputs.payload["positions"])
    ]


def finish(run, monkeypatch):
    monkeypatch.setattr(worker, "_calculate", cells)
    for chunk in run.chunks.all():
        assert worker.execute_chunk(str(chunk.pk))
    run.refresh_from_db()


def test_login_requires_csrf_even_for_anonymous_user(owner):
    client = APIClient(enforce_csrf_checks=True)
    assert (
        client.post(
            "/api/login/", {"username": "owner", "password": "test-secret-password"}, format="json"
        ).status_code
        == 403
    )
    session = client.get("/api/session/").json()
    assert session["authenticated"] is False
    response = client.post(
        "/api/login/",
        {"username": "owner", "password": "test-secret-password"},
        format="json",
        HTTP_X_CSRFTOKEN=session["csrfToken"],
    )
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert client.post("/api/logout/", {}, format="json").status_code == 403
    assert (
        client.post(
            "/api/logout/", {}, format="json", HTTP_X_CSRFTOKEN=response.json()["csrfToken"]
        ).json()["authenticated"]
        is False
    )


def test_inputs_validate_before_persistence(owner, payload):
    client = APIClient()
    client.force_login(owner)
    invalid = copy.deepcopy(payload)
    invalid["positions"][0]["quantity"] = -1
    assert (
        client.post("/api/inputs/", {"name": "bad", "inputs": invalid}, format="json").status_code
        == 400
    )
    assert InputVersion.objects.count() == PortfolioVersion.objects.count() == 0
    response = client.post("/api/inputs/", {"name": "valid", "inputs": payload}, format="json")
    assert response.status_code == 201
    assert len(response.json()["hash"]) == 64
    assert len(response.json()["version_ids"]) == 4


def test_owner_isolation_for_all_resources(owner, inputs, run, django_user_model):
    other = django_user_model.objects.create_user(username="other")
    client = APIClient()
    client.force_login(other)
    assert client.get("/api/inputs/").json() == {"items": []}
    assert client.get("/api/runs/").json() == {"items": []}
    for path in (
        f"/api/inputs/{inputs.pk}/",
        f"/api/runs/{run.pk}/",
        f"/api/runs/{run.pk}/export/?format=json",
    ):
        assert client.get(path).status_code == 404
    assert client.post(f"/api/runs/{run.pk}/retry/", {}).status_code == 404
    response = client.post(
        "/api/runs/",
        {"input_id": str(inputs.pk), "mode": "REFERENCE", "idempotency_key": "steal"},
        format="json",
    )
    assert response.status_code == 404


def test_post_run_is_durable_and_idempotent(owner, inputs):
    client = APIClient()
    client.force_login(owner)
    data = {"input_id": str(inputs.pk), "mode": "REFERENCE", "idempotency_key": "same"}
    first = client.post("/api/runs/", data, format="json")
    second = client.post("/api/runs/", data, format="json")
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert ValuationRun.objects.count() == 1
    assert (
        OutboxEvent.objects.count() == RunChunk.objects.count() == len(inputs.payload["scenarios"])
    )
    data["mode"] = "COMPARE"
    assert client.post("/api/runs/", data, format="json").status_code == 409


def test_run_and_outbox_roll_back_together(owner, inputs, monkeypatch):
    def failed_publish_rows(*args, **kwargs):
        raise RuntimeError("simulated outbox storage failure")

    monkeypatch.setattr(OutboxEvent.objects, "bulk_create", failed_publish_rows)
    with pytest.raises(RuntimeError):
        create_run(owner, inputs, "REFERENCE", "atomic")
    assert (
        ValuationRun.objects.count() == RunChunk.objects.count() == OutboxEvent.objects.count() == 0
    )


def test_same_key_cannot_select_other_inputs(owner, inputs, payload):
    create_run(owner, inputs, "REFERENCE", "same")
    different = create_inputs(owner, "other version", payload)
    with pytest.raises(IdempotencyConflict):
        create_run(owner, different, "REFERENCE", "same")


def test_snapshot_model_and_queryset_mutations_are_blocked(inputs):
    inputs.name = "changed"
    with pytest.raises(ValidationError):
        inputs.save()
    with pytest.raises(ValidationError):
        InputVersion.objects.filter(pk=inputs.pk).update(name="changed")
    with pytest.raises(ValidationError):
        inputs.delete()
    with pytest.raises(ValidationError):
        InputVersion.objects.all().delete()
    with pytest.raises(ValidationError):
        InputVersion.objects.bulk_update([inputs], ["name"])


def test_published_primary_key_cannot_be_reused_to_overwrite(inputs):
    replacement = MarketSnapshot(id=inputs.market_id, owner=inputs.owner, payload={}, hash="x" * 64)
    with pytest.raises(DatabaseError), transaction.atomic():
        replacement.save()
    assert MarketSnapshot.objects.get(pk=inputs.market_id).payload == inputs.payload["market"]


def test_postgres_raw_sql_snapshot_mutation_is_blocked(inputs):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL trigger is validated in the integration test profile")
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolios_inputversion SET name = %s WHERE id = %s", ["tampered", inputs.pk]
        )
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM portfolios_inputversion WHERE id = %s", [inputs.pk])


def test_duplicate_delivery_and_lost_ack_do_not_duplicate_results(run, monkeypatch):
    finish(run, monkeypatch)
    count = ValuationResult.objects.count()
    for chunk in run.chunks.all():
        assert worker.execute_chunk(str(chunk.pk)) is False
    assert ValuationResult.objects.count() == count == 4
    assert run.status == "COMPLETED"


def test_active_chunk_lease_rejects_duplicate_worker(run):
    chunk = run.chunks.first()
    assert worker._claim(chunk.pk) is not None
    assert worker._claim(chunk.pk) is None


def test_expired_worker_is_fenced_after_reclaim(run):
    chunk = run.chunks.select_related("run__inputs").first()
    old_token = worker._claim(chunk.pk)
    RunChunk.objects.filter(pk=chunk.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    assert worker.recover_work() >= 1
    new_token = worker._claim(chunk.pk)
    assert new_token != old_token
    assert worker._finalize(chunk.pk, old_token, cells(chunk)) is False
    assert worker._finalize(chunk.pk, new_token, cells(chunk)) is True
    assert ValuationResult.objects.filter(chunk=chunk).count() == 2


def test_failure_during_result_transaction_rolls_back_and_can_recover(run, monkeypatch):
    chunk = run.chunks.first()
    original_bulk_create = ValuationResult.objects.bulk_create

    def fail_after_insert(*args, **kwargs):
        original_bulk_create(*args, **kwargs)
        raise RuntimeError("worker loss before commit")

    monkeypatch.setattr(worker, "_calculate", cells)
    monkeypatch.setattr(ValuationResult.objects, "bulk_create", fail_after_insert)
    with pytest.raises(RuntimeError):
        worker.execute_chunk(chunk.pk)
    assert ValuationResult.objects.count() == 0
    RunChunk.objects.filter(pk=chunk.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    worker.recover_work()
    monkeypatch.setattr(ValuationResult.objects, "bulk_create", original_bulk_create)
    assert worker.execute_chunk(chunk.pk)
    assert ValuationResult.objects.count() == 2


def test_failed_base_cell_suppresses_total_and_all_stress_pnl(run, monkeypatch):
    monkeypatch.setattr(
        worker,
        "_calculate",
        lambda chunk: (
            cells(chunk, (0,))
            if chunk.scenario_index == run.provenance["base_scenario_index"]
            else cells(chunk)
        ),
    )
    for chunk in run.chunks.all():
        worker.execute_chunk(chunk.pk)
    run.refresh_from_db()
    report = run_document(run)
    assert run.status == "PARTIAL_ERROR"
    assert report["totals"][0]["value"] is None
    assert all(total["pnl"] is None for total in report["totals"])
    failed = next(cell for cell in report["results"] if cell["status"] == "FAILED")
    assert failed["reference_price"] is failed["reference_value"] is None


def test_exhausted_worker_losses_record_explicit_failures(run, settings):
    settings.CHUNK_MAX_ATTEMPTS = 1
    for chunk in run.chunks.all():
        worker._claim(chunk.pk)
        RunChunk.objects.filter(pk=chunk.pk).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
    worker.recover_work()
    run.refresh_from_db()
    assert run.status == "FAILED"
    assert run.results.count() == 4
    assert all(total["value"] is None for total in run_document(run)["totals"])


def test_outbox_republishes_after_lost_publish_ack(run):
    published = []

    def publish_then_lose_ack(chunk_id):
        published.append(chunk_id)
        raise RuntimeError("broker ack lost")

    assert worker.dispatch_pending(publish_then_lose_ack, limit=1) == 0
    assert worker.dispatch_pending(published.append, limit=2) == 2
    assert published.count(published[0]) == 2


def test_published_but_missing_queue_message_is_recovered(run, settings):
    settings.QUEUE_RECOVERY_SECONDS = 0
    assert worker.dispatch_pending(lambda chunk_id: None) == 2
    OutboxEvent.objects.update(published_at=timezone.now() - timedelta(seconds=1))
    worker.recover_work()
    assert OutboxEvent.objects.filter(published_at__isnull=True).count() == 2


def test_run_without_explicit_base_adds_recorded_base(owner, payload):
    payload["scenarios"] = payload["scenarios"][1:]
    inputs = create_inputs(owner, "no base", payload)
    run, _ = create_run(owner, inputs, "REFERENCE", "auto-base")
    assert len(inputs.payload["scenarios"]) == 1
    assert len(run.provenance["execution_scenarios"]) == 2
    assert run.provenance["base_scenario_index"] == 1


def test_retry_creates_new_run_and_exports_preserve_provenance(owner, run, monkeypatch):
    finish(run, monkeypatch)
    client = APIClient()
    client.force_login(owner)
    retry = client.post(f"/api/runs/{run.pk}/retry/", {}, format="json")
    assert retry.status_code == 202
    assert retry.json()["id"] != str(run.pk)
    assert ValuationRun.objects.get(pk=retry.json()["id"]).inputs_id == run.inputs_id
    exported = client.get(f"/api/runs/{run.pk}/export/?format=json")
    assert exported.status_code == 200
    assert exported.json()["provenance"] == run.provenance
    csv = client.get(f"/api/runs/{run.pk}/export/?format=csv")
    assert csv.status_code == 200
    assert b"scenario_complete" in csv.content and run.inputs.hash.encode() in csv.content


def test_reference_heston_execution_and_sensitivities(run):
    for chunk in run.chunks.all():
        assert worker.execute_chunk(chunk.pk)
    run.refresh_from_db()
    assert run.status == "COMPLETED", list(run.results.values_list("error", flat=True))
    report = run_document(run)
    assert all(total["complete"] for total in report["totals"])
    assert report["totals"][0]["pnl"] == 0.0
    assert report["results"][0]["sensitivities"]["sigma0_bump"] > 0


def test_compare_artifact_failure_retains_reference_values(owner, inputs):
    artifact = ModelArtifact.objects.create(
        name="missing artifact", manifest={}, manifest_hash="0" * 64, relative_path="missing-test"
    )
    run, _ = create_run(owner, inputs, "COMPARE", "compare", artifact)
    for chunk in run.chunks.all():
        worker.execute_chunk(chunk.pk)
    run.refresh_from_db()
    assert run.status == "COMPLETED"
    report = run_document(run)
    assert all(cell["ml_price"] is None and cell["ml_error"] for cell in report["results"])
    assert all(total["complete"] and not total["ml_complete"] for total in report["totals"])
