"""HTTP/configuration smoke tests, separate from numerical contract tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient


def test_health_is_public_liveness_without_database_access():
    # No django_db marker: pytest-django fails this test if a DB query is attempted.
    response = APIClient().get(reverse("health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_rejects_post():
    response = APIClient().post(reverse("health"), {}, format="json")
    assert response.status_code == 405


def test_admin_uses_django_login(client):
    response = client.get(reverse("admin:index"))
    assert response.status_code == 302
    assert response.url == reverse("admin:login") + "?next=/admin/"


def test_application_boundaries_are_registered():
    assert {
        apps.get_app_config(label).name
        for label in ("accounts", "portfolios", "marketdata", "valuations", "model_registry")
    } == {
        "apps.accounts",
        "apps.portfolios",
        "apps.marketdata",
        "apps.valuations",
        "apps.model_registry",
    }


def test_session_authentication_and_csrf_are_default():
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == [
        "rest_framework.authentication.SessionAuthentication"
    ]
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated"
    ]
    assert "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE
    assert "django.contrib.sessions.middleware.SessionMiddleware" in settings.MIDDLEWARE


def test_dispatcher_shared_task_uses_the_configured_broker():
    from apps.valuations.tasks import calculate_chunk

    assert calculate_chunk.app.conf.broker_url == settings.CELERY_BROKER_URL
    assert calculate_chunk.acks_late is True
    assert calculate_chunk.reject_on_worker_lost is True


@pytest.mark.parametrize("secret", [None, "", "   "])
def test_development_requires_explicit_secret(secret):
    project_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    environment.pop("DJANGO_SECRET_KEY", None)
    if secret is not None:
        environment["DJANGO_SECRET_KEY"] = secret
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import config.settings.development",
            str(project_root / "src"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode != 0
    assert "Set DJANGO_SECRET_KEY" in result.stderr


def test_development_uses_postgresql_and_debug_is_opt_in():
    project_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    environment.pop("DJANGO_DEBUG", None)
    environment["DJANGO_SECRET_KEY"] = "subprocess-test-key"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from config.settings import development as s; "
            "assert s.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql'; "
            "assert s.DEBUG is False",
            str(project_root / "src"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
