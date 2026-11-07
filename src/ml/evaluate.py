"""Assess an existing baseline using explicit gates and publish a new artifact."""

import argparse
import json
import shutil
from pathlib import Path

import numpy as np

from ml.dataset import dataset_hash
from ml.features import DEFAULT_SPEC
from ml.inference import ArtifactError, load_artifact, sha256_file
from ml.validation import apply_gates, validate
from quant.heston import HestonPricer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output must be a new path; existing artifacts are immutable")
    surrogate = load_artifact(args.artifact)
    with np.load(args.dataset, allow_pickle=False) as archive:
        arrays = dict(archive)
    if dataset_hash(arrays) != surrogate.manifest["dataset_sha256"]:
        raise ArtifactError("dataset SHA-256 mismatch")
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    report = validate(
        surrogate,
        HestonPricer(DEFAULT_SPEC, integration_order=144),
        arrays,
        surrogate.manifest["seed"],
    )
    report["teacher_failures"] = surrogate.manifest.get("teacher_failures", {})
    validation = apply_gates(report, gates)
    report["validation"] = validation
    args.output.mkdir(parents=True)
    shutil.copyfile(args.artifact / "model.pt", args.output / "model.pt")
    manifest = surrogate.manifest | {
        "validation": validation,
        "baseline_manifest_sha256": sha256_file(args.artifact / "manifest.json"),
    }
    (args.output / "validation_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    manifest["validation_report_sha256"] = sha256_file(args.output / "validation_report.json")
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(validation, indent=2), flush=True)
    return 0 if validation["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
