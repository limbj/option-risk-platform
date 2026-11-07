"""Django HTTP application configuration; financial code lives in quant."""

from config.celery import app as celery_app

__all__ = ("celery_app",)
