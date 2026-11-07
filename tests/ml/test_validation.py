# ruff: noqa: E402
import pytest

pytest.importorskip("torch")

from ml.validation import apply_gates


def report():
    return {
        "all_normalized_errors": {"mean": 0.001, "p99": 0.005, "maximum": 0.01},
        "portfolio_stress_pnl": {
            "gross_notional_normalized_error": {"maximum": 0.002},
            "incomplete_portfolios": 0,
        },
        "bounds_violations_at_normalized_tolerance_1e_minus_7": 0,
        "maximum_normalized_put_call_parity_residual": 1e-16,
        "out_of_domain": {"rejected": 5},
    }


GATES = {
    "normalized_mean": 0.002,
    "normalized_p99": 0.006,
    "normalized_maximum": 0.02,
    "portfolio_pnl_maximum": 0.003,
}


def test_quality_gate_pass_does_not_authorize_authoritative_ml_risk():
    validation = apply_gates(report(), GATES)
    assert validation["status"] == "passed"
    assert validation["use"] == "comparison_only_reference_remains_authoritative"
    assert validation["performance_gate"] == "report_only_no_minimum_speed_claim"


def test_tail_error_fails_the_gate_even_when_mean_error_passes():
    result = report()
    result["all_normalized_errors"]["maximum"] = 0.03
    validation = apply_gates(result, GATES)
    assert validation["status"] == "failed"
    assert validation["checks"]["normalized_mean"]
    assert not validation["checks"]["normalized_maximum"]


def test_incomplete_portfolio_is_a_failed_gate():
    result = report()
    result["portfolio_stress_pnl"]["incomplete_portfolios"] = 1
    assert apply_gates(result, GATES)["status"] == "failed"


@pytest.mark.parametrize("passed", [True, False])
def test_evaluation_cli_propagates_gate_failure_after_preserving_the_report(
    tmp_path, monkeypatch, passed
):
    import json
    from types import SimpleNamespace

    import numpy as np

    from ml import evaluate
    from ml.dataset import dataset_hash

    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "model.pt").write_bytes(b"already-validated-model")
    (baseline / "manifest.json").write_text("{}", encoding="utf-8")
    arrays = {"random_x": np.asarray([[0.0, 1.0, 0.03, 0.2]])}
    dataset_path = tmp_path / "dataset.npz"
    np.savez(dataset_path, **arrays)
    gate_path = tmp_path / "gates.json"
    gate_path.write_text(json.dumps(GATES), encoding="utf-8")
    manifest = {"dataset_sha256": dataset_hash(arrays), "seed": 1729}
    monkeypatch.setattr(evaluate, "load_artifact", lambda _: SimpleNamespace(manifest=manifest))
    measured = report()
    if not passed:
        measured["all_normalized_errors"]["maximum"] = 0.03
    monkeypatch.setattr(evaluate, "validate", lambda *args: measured)
    output = tmp_path / "assessed"
    exit_code = evaluate.main(
        [
            "--artifact",
            str(baseline),
            "--dataset",
            str(dataset_path),
            "--gates",
            str(gate_path),
            "--output",
            str(output),
        ]
    )
    assert exit_code == (0 if passed else 2)
    assessment = json.loads((output / "validation_report.json").read_text(encoding="utf-8"))
    stored = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    expected = "passed" if passed else "failed"
    assert assessment["validation"]["status"] == stored["validation"]["status"] == expected
    assert (output / "model.pt").read_bytes() == b"already-validated-model"
