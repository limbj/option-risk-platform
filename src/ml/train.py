"""Reproducible offline Heston-surrogate training; python -m ml.train --help."""

import argparse
import copy
import json
import platform
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import numpy as np
import torch

from ml.dataset import dataset_hash, generate_dataset
from ml.features import DEFAULT_SPEC, DOMAIN, FEATURE_ORDER, HELDOUT_REGION
from ml.inference import Surrogate, sha256_file
from ml.network import ARCHITECTURE, PricingMLP
from ml.validation import apply_gates, validate
from quant.heston import HestonPricer


def fit(arrays: dict, epochs: int, seed: int):
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    x = torch.tensor(arrays["train_x"], dtype=torch.float32)
    y = torch.tensor(arrays["train_y"], dtype=torch.float32)
    tune_x = torch.tensor(arrays["tune_x"], dtype=torch.float32)
    tune_y = torch.tensor(arrays["tune_y"], dtype=torch.float32)
    mean, scale = x.mean(0).tolist(), x.std(0).tolist()
    model = PricingMLP(mean, scale)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.002, weight_decay=1e-6)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    best_loss, best_state, best_epoch = float("inf"), None, 0
    for epoch in range(epochs):
        model.train()
        indices = torch.randperm(len(x))
        for selected in indices.split(512):
            optimizer.zero_grad(set_to_none=True)
            loss = ((model(x[selected]) - y[selected]) ** 2).mean() * 10_000
            loss.backward()
            optimizer.step()
        scheduler.step()
        model.eval()
        with torch.inference_mode():
            tune_loss = float(((model(tune_x) - tune_y) ** 2).mean())
        if tune_loss < best_loss:
            best_loss, best_state, best_epoch = (
                tune_loss,
                copy.deepcopy(model.state_dict()),
                epoch + 1,
            )
        if (epoch + 1) % 50 == 0 or epoch == 0:
            print(f"epoch={epoch + 1} tune_rmse={tune_loss**0.5:.6g}", flush=True)
    model.load_state_dict(best_state)
    return model.eval(), mean, scale, {"best_epoch": best_epoch, "tuning_mse": best_loss}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/demo"))
    parser.add_argument("--dataset", type=Path, default=Path("data/demo_dataset.npz"))
    parser.add_argument("--samples", type=int, default=16_000)
    parser.add_argument("--epochs", type=int, default=350)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--gates", type=Path)
    args = parser.parse_args(argv)
    if args.samples < 128 or args.epochs < 1:
        parser.error("samples must be >=128 and epochs >=1")
    if args.output.exists() or args.dataset.exists():
        parser.error("output and dataset must be new paths; artifacts are immutable")
    pricer = HestonPricer(DEFAULT_SPEC, integration_order=144)
    started = perf_counter()
    print(
        f"generating {args.samples} training labels plus independent validation splits", flush=True
    )
    arrays, teacher_failures = generate_dataset(pricer, args.samples, args.seed)
    generation_seconds = perf_counter() - started
    args.dataset.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.dataset, **arrays)
    started = perf_counter()
    network, mean, scale, fit_result = fit(arrays, args.epochs, args.seed)
    training_seconds = perf_counter() - started
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "feature_order": FEATURE_ORDER,
        "preprocessing": {"mean": mean, "scale": scale},
        "domain": DOMAIN,
        "heldout_region": HELDOUT_REGION,
        "model_spec": asdict(DEFAULT_SPEC),
        "q": 0,
        "day_count": "ACT/365F",
        "architecture": ARCHITECTURE,
        "dtype": "float32",
        "device": "cpu",
        "seed": args.seed,
        "dataset_sha256": dataset_hash(arrays),
        "dataset_file_sha256": sha256_file(args.dataset),
        "teacher_failures": teacher_failures,
        "dataset_counts": {
            key[:-2]: len(value) for key, value in arrays.items() if key.endswith("_x")
        },
        "teacher": {
            "engine": "QuantLib.AnalyticHestonEngine",
            "integration_order": 144,
            "dtype": "float64",
            "valuation_date": "2026-11-08",
        },
        "software_versions": {name: version(name) for name in ("torch", "numpy", "QuantLib")}
        | {"python": platform.python_version(), "platform": platform.platform()},
        "training": {
            "epochs": args.epochs,
            "batch_size": 512,
            "optimizer": "AdamW",
            "initial_lr": 0.002,
            "schedule": "cosine",
            "torch_threads": 1,
            "deterministic_algorithms": True,
            "selection_split": "tune",
            **fit_result,
        },
        "source_hashes": {
            path.name: sha256_file(path) for path in sorted(Path(__file__).parent.glob("*.py"))
        },
    }
    surrogate = Surrogate(network, manifest)
    report = validate(surrogate, pricer, arrays, args.seed)
    report["teacher_failures"] = teacher_failures
    report["generation_seconds"] = generation_seconds
    report["training_seconds"] = training_seconds
    report["baseline_policy"] = (
        "Measured errors; no production-risk authorization. "
        "Pass --gates to evaluate explicit quality thresholds."
    )
    if args.gates:
        gates = json.loads(args.gates.read_text(encoding="utf-8"))
        validation = apply_gates(report, gates)
    else:
        validation = {
            "status": "baseline",
            "use": "comparison_only_reference_remains_authoritative",
            "performance_gate": "report_only_no_minimum_speed_claim",
        }
    report["validation"] = validation
    args.output.mkdir(parents=True)
    torch.save(network.state_dict(), args.output / "model.pt")
    manifest["weights_sha256"] = sha256_file(args.output / "model.pt")
    manifest["validation"] = validation
    (args.output / "validation_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    manifest["validation_report_sha256"] = sha256_file(args.output / "validation_report.json")
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "errors": report["all_normalized_errors"],
                "validation": validation,
                "timing": report["timing"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 2 if validation["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
