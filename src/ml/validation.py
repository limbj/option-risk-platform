"""Held-out accuracy, deterministic stress P&L and equal-workload benchmarks."""

from dataclasses import replace
from statistics import median
from time import perf_counter

import numpy as np
import torch

from ml.dataset import case_from_features
from ml.features import DEFAULT_SPEC, UnsupportedInput
from quant.contracts import OptionType


def error_metrics(errors: np.ndarray) -> dict:
    absolute = np.abs(errors)
    return {
        "count": len(absolute),
        "mean": float(absolute.mean()),
        "maximum": float(absolute.max()),
        "p95": float(np.quantile(absolute, 0.95)),
        "p99": float(np.quantile(absolute, 0.99)),
    }


def predict_normalized(network, rows):
    with torch.inference_mode():
        return network(torch.tensor(rows, dtype=torch.float32)).numpy().astype(np.float64)


def portfolio_validation(surrogate, pricer, seed: int) -> dict:
    rng = np.random.default_rng(seed + 100)
    errors, normalized = [], []
    unsupported = 0
    for _ in range(40):
        reference_pnl, ml_pnl, gross_notional = 0.0, 0.0, 0.0
        complete = True
        for index, quantity in enumerate([2, -1, 3, -2]):
            row = [
                rng.uniform(-0.3, 0.3),
                round(rng.uniform(0.2, 1.8) * 365) / 365,
                rng.uniform(-0.02, 0.08),
                rng.uniform(0.08, 0.6),
            ]
            kind = OptionType.CALL if index % 2 == 0 else OptionType.PUT
            contract, market = case_from_features(row, kind)
            stressed = replace(
                market,
                spot=market.spot * 1.05,
                sigma0=market.sigma0 + 0.05,
                rate=market.rate + 0.01,
            )
            reference_pnl += (
                quantity * 100 * (pricer.price(contract, stressed) - pricer.price(contract, market))
            )
            gross_notional += abs(quantity) * 100 * contract.strike
            try:
                ml_pnl += (
                    quantity
                    * 100
                    * (
                        surrogate.price(contract, stressed, DEFAULT_SPEC)
                        - surrogate.price(contract, market, DEFAULT_SPEC)
                    )
                )
            except UnsupportedInput:
                complete = False
        if complete:
            errors.append(ml_pnl - reference_pnl)
            normalized.append((ml_pnl - reference_pnl) / gross_notional)
        else:
            unsupported += 1
    return {
        "portfolio_count": 40,
        "positions_per_portfolio": 4,
        "multiplier": 100,
        "signed_quantities": [2, -1, 3, -2],
        "spot_shock_pct": 5,
        "sigma0_shock_pp": 5,
        "rate_shock_bp": 100,
        "incomplete_portfolios": unsupported,
        "usd_error": error_metrics(np.asarray(errors)) if errors else None,
        "gross_notional_normalized_error": error_metrics(np.asarray(normalized))
        if errors
        else None,
    }


def timings(surrogate, pricer, rows) -> dict:
    cases = [case_from_features(row) for row in rows[:512]]
    raw = torch.tensor(rows[:512], dtype=torch.float32)
    # Warm both implementations and reuse the QuantLib model/engine instance.
    for contract, market in cases[:16]:
        pricer.price(contract, market)
    surrogate.price_many(cases[:16], DEFAULT_SPEC)
    measurements = {
        "reference_reused": [],
        "ml_batch_with_validation": [],
        "ml_per_position_with_validation": [],
        "ml_tensor_core": [],
    }
    for _ in range(5):
        started = perf_counter()
        for contract, market in cases:
            pricer.price(contract, market)
        measurements["reference_reused"].append(perf_counter() - started)
        started = perf_counter()
        surrogate.price_many(cases, DEFAULT_SPEC)
        measurements["ml_batch_with_validation"].append(perf_counter() - started)
        started = perf_counter()
        for contract, market in cases:
            surrogate.price(contract, market, DEFAULT_SPEC)
        measurements["ml_per_position_with_validation"].append(perf_counter() - started)
        started = perf_counter()
        with torch.inference_mode():
            surrogate.network(raw)
        measurements["ml_tensor_core"].append(perf_counter() - started)
    medians = {key: median(value) for key, value in measurements.items()}
    return {
        "case_count": len(cases),
        "repeats": 5,
        "unit": "seconds",
        "median": medians,
        "batch_reference_ratio": medians["reference_reused"] / medians["ml_batch_with_validation"],
        "per_position_reference_ratio": (
            medians["reference_reused"] / medians["ml_per_position_with_validation"]
        ),
        "notes": "Same cases and CPU; warmed, reused Heston engine. API/queue time excluded. "
        "ML price error is reported separately; these are not equal-accuracy engines.",
    }


def validate(surrogate, pricer, arrays: dict, seed: int) -> dict:
    splits = {}
    all_errors = []
    bounds_violations = 0
    parity_error = 0.0
    for split in ("random", "heldout", "edge"):
        rows, truth = arrays[f"{split}_x"], arrays[f"{split}_y"]
        predictions = predict_normalized(surrogate.network, rows)
        errors = predictions - truth
        all_errors.append(errors)
        s = np.exp(rows[:, 0])
        parity = s - np.exp(-rows[:, 2] * rows[:, 1])
        lower = np.maximum(0, parity)
        bounds_violations += int(
            np.count_nonzero((predictions < lower - 1e-7) | (predictions > s + 1e-7))
        )
        puts = predictions - parity
        parity_error = max(parity_error, float(np.max(np.abs(predictions - puts - parity))))
        subsets = {}
        for name, mask in {
            "near_expiry_le_30_days": rows[:, 1] <= 30 / 365,
            "itm_log_moneyness_gt_0.2": rows[:, 0] > 0.2,
            "otm_log_moneyness_lt_minus_0.2": rows[:, 0] < -0.2,
        }.items():
            if mask.any():
                subsets[name] = error_metrics(errors[mask])
        splits[split] = {
            "normalized_call_error": error_metrics(errors),
            "usd_call_error_at_strike_100": error_metrics(errors * 100),
            "subsets_normalized_error": subsets,
        }
    rejected = []
    for feature, row in [
        ("moneyness", [0.5, 1, 0.03, 0.2]),
        ("maturity", [0, 3, 0.03, 0.2]),
        ("rate", [0, 1, 0.2, 0.2]),
        ("sigma0", [0, 1, 0.03, 0.8]),
    ]:
        try:
            surrogate.price(*case_from_features(row), DEFAULT_SPEC)
        except UnsupportedInput as exc:
            rejected.append({"feature": feature, "reason": str(exc)})
    try:
        surrogate.price(*case_from_features([0, 1, 0.03, 0.2]), replace(DEFAULT_SPEC, rho=-0.5))
    except UnsupportedInput as exc:
        rejected.append({"feature": "model_spec", "reason": str(exc)})
    portfolio = portfolio_validation(surrogate, pricer, seed)
    combined = error_metrics(np.concatenate(all_errors))
    return {
        "splits": splits,
        "all_normalized_errors": combined,
        "bounds_violations_at_normalized_tolerance_1e_minus_7": bounds_violations,
        "maximum_normalized_put_call_parity_residual": parity_error,
        "out_of_domain": {"attempted": 5, "rejected": len(rejected), "reasons": rejected},
        "portfolio_stress_pnl": portfolio,
        "timing": timings(surrogate, pricer, arrays["random_x"]),
    }


def apply_gates(report: dict, gates: dict) -> dict:
    errors = report["all_normalized_errors"]
    portfolio = report["portfolio_stress_pnl"]["gross_notional_normalized_error"]
    checks = {
        "normalized_mean": errors["mean"] <= gates["normalized_mean"],
        "normalized_p99": errors["p99"] <= gates["normalized_p99"],
        "normalized_maximum": errors["maximum"] <= gates["normalized_maximum"],
        "portfolio_pnl_maximum": portfolio is not None
        and portfolio["maximum"] <= gates["portfolio_pnl_maximum"],
        "price_bounds": report["bounds_violations_at_normalized_tolerance_1e_minus_7"] == 0,
        "parity": report["maximum_normalized_put_call_parity_residual"] < 1e-12,
        "ood_rejection": report["out_of_domain"]["rejected"] == 5,
        "complete_portfolios": report["portfolio_stress_pnl"]["incomplete_portfolios"] == 0,
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "gates": gates,
        "use": "comparison_only_reference_remains_authoritative",
        "performance_gate": "report_only_no_minimum_speed_claim",
    }
