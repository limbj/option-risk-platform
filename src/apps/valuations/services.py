"""Application use cases shared by HTTP and task orchestration."""

import hashlib
import importlib.metadata
import json
import os
import platform
import uuid
from dataclasses import asdict
from datetime import date

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.marketdata.models import MarketSnapshot, ScenarioSetVersion
from apps.model_registry.models import ModelArtifact, ModelVersion
from apps.portfolios.models import InputVersion, PortfolioVersion
from apps.valuations.models import OutboxEvent, RunChunk, ValuationRun
from quant.inputs import parse_inputs


class IdempotencyConflict(Exception):
    pass


def json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Unsupported value: {type(value).__name__}")


def canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=json_default
    )


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def normalized_inputs(payload):
    return json.loads(canonical_json(asdict(parse_inputs(payload))))


@transaction.atomic
def create_inputs(owner, name, payload):
    normalized = normalized_inputs(payload)
    portfolio = PortfolioVersion.objects.create(
        owner=owner, payload=normalized["positions"], hash=digest(normalized["positions"])
    )
    market = MarketSnapshot.objects.create(
        owner=owner, payload=normalized["market"], hash=digest(normalized["market"])
    )
    scenarios = ScenarioSetVersion.objects.create(
        owner=owner, payload=normalized["scenarios"], hash=digest(normalized["scenarios"])
    )
    model = ModelVersion.objects.create(
        owner=owner, payload=normalized["model"], hash=digest(normalized["model"])
    )
    return InputVersion.objects.create(
        owner=owner,
        name=name,
        payload=normalized,
        hash=digest(normalized),
        portfolio=portfolio,
        market=market,
        scenarios=scenarios,
        model=model,
    )


def version_ids(inputs):
    return {
        "portfolio": str(inputs.portfolio_id),
        "market": str(inputs.market_id),
        "scenarios": str(inputs.scenarios_id),
        "model": str(inputs.model_id),
    }


def verify_inputs(inputs):
    if digest(inputs.payload) != inputs.hash:
        raise ValueError("Pinned input hash mismatch")
    for component, payload_key in (
        ("portfolio", "positions"),
        ("market", "market"),
        ("scenarios", "scenarios"),
        ("model", "model"),
    ):
        record = getattr(inputs, component)
        if (
            record.owner_id != inputs.owner_id
            or digest(record.payload) != record.hash
            or record.payload != inputs.payload[payload_key]
        ):
            raise ValueError(f"Pinned {component} snapshot integrity mismatch")
    return parse_inputs(inputs.payload)


def code_version():
    hasher = hashlib.sha256()
    for path in sorted((settings.BASE_DIR / "src").rglob("*.py")):
        hasher.update(str(path.relative_to(settings.BASE_DIR)).replace("\\", "/").encode())
        hasher.update(path.read_bytes())
    return {
        "revision": os.environ.get("CODE_VERSION", "uncommitted"),
        "source_sha256": hasher.hexdigest(),
    }


def software_versions():
    versions = {"python": platform.python_version()}
    for package in ("Django", "numpy", "scipy", "QuantLib", "torch", "celery"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def execution_scenarios(inputs):
    scenarios = list(inputs.payload["scenarios"])
    for index, scenario in enumerate(scenarios):
        if all(
            scenario[field] == 0 for field in ("spot_shock_pct", "sigma0_shock_pp", "rate_shock_bp")
        ):
            return scenarios, index
    return scenarios + [
        {"name": "__base__", "spot_shock_pct": 0.0, "sigma0_shock_pp": 0.0, "rate_shock_bp": 0.0}
    ], len(scenarios)


def verify_run_inputs(run):
    bundle = verify_inputs(run.inputs)
    scenarios, base_index = execution_scenarios(run.inputs)
    expected = {
        "input_hash": run.inputs.hash,
        "version_ids": version_ids(run.inputs),
        "component_hashes": {
            name: getattr(run.inputs, name).hash
            for name in ("portfolio", "market", "scenarios", "model")
        },
        "valuation_date": run.inputs.payload["market"]["valuation_date"],
        "execution_scenarios": scenarios,
        "base_scenario_index": base_index,
        "artifact_id": str(run.artifact_id) if run.artifact_id else None,
        "artifact_manifest_hash": run.artifact.manifest_hash if run.artifact_id else None,
    }
    if run.owner_id != run.inputs.owner_id or any(
        run.provenance.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("Run provenance differs from pinned input/model versions")
    return bundle


def create_run(owner, inputs, mode, idempotency_key, artifact=None):
    if inputs.owner_id != owner.pk:
        raise ValidationError("Input owner mismatch")
    if mode not in {"REFERENCE", "COMPARE"}:
        raise ValidationError("mode must be REFERENCE or COMPARE")
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
        raise ValidationError("idempotency_key must contain 1 to 128 characters")
    # The requested artifact ID is part of idempotency even when the server chooses a default.
    request_hash = digest(
        {
            "input_id": str(inputs.pk),
            "mode": mode,
            "artifact_id": str(artifact.pk) if artifact else None,
        }
    )
    previous = ValuationRun.objects.filter(owner=owner, idempotency_key=idempotency_key).first()
    if previous:
        if previous.request_hash != request_hash:
            raise IdempotencyConflict("Idempotency key was used for a different request")
        return previous, False
    verify_inputs(inputs)
    if mode == "COMPARE" and artifact is None:
        artifact = ModelArtifact.objects.order_by("-created_at").first()
        if artifact is None:
            raise ValidationError("COMPARE requires a registered model artifact")
    if mode == "REFERENCE" and artifact is not None:
        raise ValidationError("REFERENCE does not accept artifact_id")
    scenarios, base_index = execution_scenarios(inputs)
    provenance = {
        "input_hash": inputs.hash,
        "version_ids": version_ids(inputs),
        "component_hashes": {
            name: getattr(inputs, name).hash
            for name in ("portfolio", "market", "scenarios", "model")
        },
        "valuation_date": inputs.payload["market"]["valuation_date"],
        "engine": "QuantLib.AnalyticHestonEngine",
        "model": "Heston",
        "q": 0.0,
        "day_count": "ACT/365F",
        "currency": "USD",
        "integration_order": 144,
        "sensitivity_settings": {
            "method": "central finite difference",
            "spot_relative_bump": 1e-4,
            "sigma0_bump": 1e-4,
        },
        "sensitivity_units": {
            "delta": "per unit spot",
            "gamma": "per unit spot squared",
            "initial_volatility_sensitivity": "per 1.0 decimal sigma0",
        },
        "stress_semantics": "instantaneous; spot percent, sigma0 percentage points, rate bp",
        "execution_scenarios": scenarios,
        "base_scenario_index": base_index,
        "code_version": code_version(),
        "software_versions": software_versions(),
        "artifact_id": str(artifact.pk) if artifact else None,
        "artifact_manifest_hash": artifact.manifest_hash if artifact else None,
        "authoritative_engine": "reference",
        "is_var_or_probability_forecast": False,
    }
    try:
        with transaction.atomic():
            run = ValuationRun.objects.create(
                owner=owner,
                inputs=inputs,
                mode=mode,
                artifact=artifact,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                provenance=provenance,
            )
            chunks = RunChunk.objects.bulk_create(
                [RunChunk(run=run, scenario_index=index) for index in range(len(scenarios))]
            )
            OutboxEvent.objects.bulk_create([OutboxEvent(chunk=chunk) for chunk in chunks])
        return run, True
    except IntegrityError:
        previous = ValuationRun.objects.filter(owner=owner, idempotency_key=idempotency_key).first()
        if previous is None:
            raise
        if previous.request_hash != request_hash:
            raise IdempotencyConflict("Idempotency key was used for a different request") from None
        return previous, False


def retry_run(owner, previous):
    if previous.status not in {"COMPLETED", "PARTIAL_ERROR", "FAILED"}:
        raise ValidationError("Only finished runs can be retried")
    # Retry always creates a new run; published result cells are never overwritten.
    return create_run(owner, previous.inputs, previous.mode, str(uuid.uuid4()), previous.artifact)[
        0
    ]
