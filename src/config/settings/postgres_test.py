"""Integration tests against a disposable PostgreSQL database."""

from .base import *  # noqa: F403

SECRET_KEY = "test-only-postgres-key-never-use-for-application-deployment"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
