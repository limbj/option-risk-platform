"""Expose verified published validation reports without importing an ML runtime."""

import hashlib
import json
from pathlib import Path

from django.conf import settings


def artifact_document(record):
    document = {
        "id": str(record.pk),
        "name": record.name,
        "manifest": record.manifest,
        "hash": record.manifest_hash,
        "validation_report": None,
        "report_error": None,
    }
    try:
        root = Path(settings.ARTIFACT_ROOT).resolve()
        directory = (root / record.relative_path).resolve()
        if not directory.is_relative_to(root):
            raise ValueError("Artifact path escapes the configured root")
        manifest_path = (directory / "manifest.json").resolve()
        report_path = (directory / "validation_report.json").resolve()
        if not manifest_path.is_relative_to(directory) or not report_path.is_relative_to(directory):
            raise ValueError("Artifact file path escapes its published directory")
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != record.manifest_hash:
            raise ValueError("Published manifest SHA256 mismatch")
        raw_report = report_path.read_bytes()
        expected_hash = record.manifest.get("validation_report_sha256")
        if hashlib.sha256(raw_report).hexdigest() != expected_hash:
            raise ValueError("Published validation report SHA256 mismatch")

        def reject_nonfinite(value):
            raise ValueError("Validation report contains a non-finite number")

        report = json.loads(raw_report, parse_constant=reject_nonfinite)
        if not isinstance(report, dict):
            raise ValueError("Validation report must be a JSON object")
        document["validation_report"] = report
    except (OSError, ValueError, TypeError) as exc:
        document["report_error"] = f"{type(exc).__name__}: {exc}"
    return document
