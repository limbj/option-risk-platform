"""Local development settings. Supply secrets through the environment."""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import SECRET_KEY

if not SECRET_KEY.strip():
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY before starting Django. "
        "For local development, copy .env.example to .env and use uv run --env-file .env."
    )

_debug_value = os.environ.get("DJANGO_DEBUG", "false").lower()
if _debug_value not in {"true", "false", "1", "0"}:
    raise ImproperlyConfigured("DJANGO_DEBUG must be true, false, 1, or 0.")
DEBUG = _debug_value in {"true", "1"}
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
