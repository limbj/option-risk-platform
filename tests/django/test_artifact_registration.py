"""Published model bytes survive reuse of an offline training output directory."""

# ruff: noqa: E402
import io
import json
from dataclasses import asdict

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

torch = pytest.importorskip("torch")

from rest_framework.test import APIClient

from apps.model_registry.models import ModelArtifact
from ml.features import DEFAULT_SPEC, DOMAIN, FEATURE_ORDER
from ml.inference import load_artifact, sha256_file
from ml.network import ARCHITECTURE, PricingMLP

pytestmark = pytest.mark.django_db


@pytest.fixture
def training_output(tmp_path, settings):
    settings.ARTIFACT_ROOT = tmp_path
    source = tmp_path / "training-output"
    source.mkdir()
    mean, scale = [0, 1, 0.03, 0.2], [0.2, 0.5, 0.03, 0.1]
    network = PricingMLP(mean, scale)
    torch.save(network.state_dict(), source / "model.pt")
    (source / "validation_report.json").write_text("{}", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "feature_order": FEATURE_ORDER,
        "domain": DOMAIN,
        "architecture": ARCHITECTURE,
        "model_spec": asdict(DEFAULT_SPEC),
        "dtype": "float32",
        "device": "cpu",
        "q": 0,
        "day_count": "ACT/365F",
        "preprocessing": {"mean": mean, "scale": scale},
        "weights_sha256": sha256_file(source / "model.pt"),
        "validation_report_sha256": sha256_file(source / "validation_report.json"),
        "validation": {"status": "baseline"},
    }
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return source


def test_registration_is_idempotent_and_preserves_published_bytes(training_output, settings):
    for _ in range(2):
        call_command("register_artifact", directory=str(training_output), stdout=io.StringIO())
    assert ModelArtifact.objects.count() == 1
    record = ModelArtifact.objects.get()
    archived = settings.ARTIFACT_ROOT / record.relative_path
    assert archived != training_output
    assert record.relative_path == f"registered/{record.manifest_hash}"
    (training_output / "model.pt").write_bytes(b"new training run replaced its output")
    (training_output / "validation_report.json").write_text("new report", encoding="utf-8")
    assert load_artifact(archived).manifest == record.manifest


def test_registration_refuses_to_overwrite_corrupted_archive(training_output, settings):
    call_command("register_artifact", directory=str(training_output), stdout=io.StringIO())
    record = ModelArtifact.objects.get()
    archived = settings.ARTIFACT_ROOT / record.relative_path
    (archived / "model.pt").write_bytes(b"corruption")
    with pytest.raises(CommandError, match="archive validation"):
        call_command("register_artifact", directory=str(training_output), stdout=io.StringIO())
    assert (archived / "model.pt").read_bytes() == b"corruption"
    assert ModelArtifact.objects.count() == 1


@pytest.mark.parametrize("corrupted_file", ["manifest.json", "validation_report.json"])
def test_model_api_returns_only_verified_report(
    training_output, settings, django_user_model, corrupted_file
):
    call_command("register_artifact", directory=str(training_output), stdout=io.StringIO())
    client = APIClient()
    client.force_login(django_user_model.objects.create_user(username="report-reader"))
    valid = client.get("/api/models/")
    assert valid.status_code == 200
    assert valid.json()["items"][0]["validation_report"] == {}
    assert valid.json()["items"][0]["report_error"] is None
    record = ModelArtifact.objects.get()
    archived = settings.ARTIFACT_ROOT / record.relative_path
    (archived / corrupted_file).write_text("{}", encoding="utf-8")
    if corrupted_file == "validation_report.json":
        (archived / corrupted_file).write_text('{"modified":true}', encoding="utf-8")
    invalid = client.get("/api/models/")
    assert invalid.status_code == 200
    assert invalid.json()["items"][0]["validation_report"] is None
    assert "SHA256 mismatch" in invalid.json()["items"][0]["report_error"]
