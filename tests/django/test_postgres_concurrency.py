"""Real row-lock and unique-constraint checks; SQLite cannot establish this evidence."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.conf import settings
from django.db import close_old_connections, connection, connections

from apps.valuations.models import ValuationRun
from apps.valuations.services import create_inputs, create_run
from apps.valuations.worker import _claim

pytestmark = pytest.mark.django_db(transaction=True)


def concurrent_calls(function):
    barrier = Barrier(2)

    def invoke():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return function()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke) for _ in range(2)]
        return [future.result(timeout=30) for future in futures]


def test_concurrent_requests_and_chunk_claims_are_unique(django_user_model):
    if connection.vendor != "postgresql":
        pytest.skip("Requires real PostgreSQL row locks")
    owner = django_user_model.objects.create_user(username="concurrent-owner")
    payload = json.loads((settings.BASE_DIR / "examples" / "stage1_inputs.json").read_text())
    inputs = create_inputs(owner, "Concurrency fixture", payload)
    returned = concurrent_calls(lambda: create_run(owner, inputs, "REFERENCE", "same-request"))
    assert returned[0][0].pk == returned[1][0].pk
    assert sorted(created for _, created in returned) == [False, True]
    assert ValuationRun.objects.count() == 1
    chunk_id = returned[0][0].chunks.first().pk
    claims = concurrent_calls(lambda: _claim(chunk_id))
    assert sum(token is not None for token in claims) == 1
