"""Fast Django smoke tests only; persistence validation must use PostgreSQL."""

from .base import *  # noqa: F403

SECRET_KEY = "test-only-key-never-use-for-an-application-deployment"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
