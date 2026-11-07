"""Local auto-entry creates a normal session and preserves the existing security boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_local_demo_session_auto_entry_persists_and_still_requires_csrf(
    settings, django_user_model
):
    settings.LOCAL_DEMO_MODE = True
    demo = django_user_model.objects.create_user(username="demo")
    client = APIClient(enforce_csrf_checks=True)
    assert client.get("/api/inputs/").status_code == 403
    response = client.get("/api/session/")
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["localDemoMode"] is True
    assert response.json()["user"] == {"id": demo.pk, "username": "demo"}
    assert client.get("/api/inputs/").status_code == 200
    assert client.post("/api/inputs/", {}, format="json").status_code == 403
    with_csrf = client.post(
        "/api/inputs/", {}, format="json", HTTP_X_CSRFTOKEN=response.json()["csrfToken"]
    )
    assert with_csrf.status_code == 400  # Auth/CSRF pass; input schema validation now runs.
    assert client.get("/api/session/").json()["user"]["id"] == demo.pk


@pytest.mark.django_db
def test_local_demo_preserves_an_existing_other_user_session(settings, django_user_model):
    settings.LOCAL_DEMO_MODE = True
    django_user_model.objects.create_user(username="demo")
    other = django_user_model.objects.create_user(username="other")
    client = APIClient()
    client.force_login(other)
    response = client.get("/api/session/")
    assert response.status_code == 200
    assert response.json()["user"] == {"id": other.pk, "username": "other"}


@pytest.mark.django_db
def test_auto_entry_cannot_access_another_owners_inputs(settings, django_user_model):
    from apps.valuations.services import create_inputs

    settings.LOCAL_DEMO_MODE = True
    django_user_model.objects.create_user(username="demo")
    other = django_user_model.objects.create_user(username="other")
    payload = json.loads((settings.BASE_DIR / "examples" / "demo_inputs.json").read_text())
    inputs = create_inputs(other, "Private input", payload)
    client = APIClient()
    assert client.get("/api/session/").status_code == 200
    assert client.get("/api/inputs/").json() == {"items": []}
    assert client.get(f"/api/inputs/{inputs.pk}/").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("inactive_demo_exists", [False, True])
def test_missing_or_inactive_demo_returns_actionable_503(
    settings, django_user_model, inactive_demo_exists
):
    settings.LOCAL_DEMO_MODE = True
    if inactive_demo_exists:
        django_user_model.objects.create_user(username="demo", is_active=False)
    client = APIClient()
    response = client.get("/api/session/?username=somebody-else")
    assert response.status_code == 503
    assert response.json()["authenticated"] is False
    assert response.json()["localDemoMode"] is True
    assert "seed_demo" in response.json()["detail"]
    assert django_user_model.objects.count() == int(inactive_demo_exists)


def test_disabled_mode_remains_anonymous_without_database_access(settings):
    settings.LOCAL_DEMO_MODE = False
    response = APIClient().get("/api/session/")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert response.json()["localDemoMode"] is False


def import_settings(profile, demo_mode):
    project_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    environment.pop("LOCAL_DEMO_MODE", None)
    if demo_mode is not None:
        environment["LOCAL_DEMO_MODE"] = demo_mode
    environment["DJANGO_SECRET_KEY"] = "test-secret-" * 6
    environment["DJANGO_ALLOWED_HOSTS"] = "example.test"
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import importlib, sys; sys.path.insert(0, sys.argv[1]); "
            "settings = importlib.import_module('config.settings.' + sys.argv[2]); "
            "print(settings.LOCAL_DEMO_MODE)",
            str(project_root / "src"),
            profile,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


@pytest.mark.parametrize("value", ["true", "1", " TRUE "])
def test_production_refuses_local_auto_entry(value):
    result = import_settings("production", value)
    assert result.returncode != 0
    assert "LOCAL_DEMO_MODE must be disabled in production" in result.stderr


@pytest.mark.parametrize("value", [None, "false", "0"])
def test_production_keeps_local_demo_disabled(value):
    result = import_settings("production", value)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


@pytest.mark.parametrize("value,expected", [(None, False), ("false", False), ("true", True)])
def test_development_requires_explicit_local_demo_opt_in(value, expected):
    result = import_settings("development", value)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected)
