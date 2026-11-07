FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.12-slim-bookworm

COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --extra ml --no-install-project
COPY src ./src
COPY manage.py README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --extra ml
COPY tests ./tests
COPY examples ./examples
RUN python manage.py collectstatic --noinput --settings=config.settings.test
RUN useradd --create-home --uid 10001 appuser && chown appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60"]
