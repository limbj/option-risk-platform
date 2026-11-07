# ruff: noqa: E402
import json
from dataclasses import asdict, replace
from datetime import date

import pytest

torch = pytest.importorskip("torch")

from ml.features import DEFAULT_SPEC, DOMAIN, FEATURE_ORDER, UnsupportedInput
from ml.inference import ArtifactError, load_artifact, sha256_file
from ml.network import ARCHITECTURE, PricingMLP
from quant.contracts import MarketSnapshot, OptionContract, OptionType


@pytest.fixture
def artifact(tmp_path):
    torch.manual_seed(1729)
    network = PricingMLP([0, 1, 0.03, 0.2], [0.2, 0.5, 0.03, 0.1])
    torch.save(network.state_dict(), tmp_path / "model.pt")
    (tmp_path / "validation_report.json").write_text("{}", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "feature_order": FEATURE_ORDER,
        "domain": DOMAIN,
        "architecture": ARCHITECTURE,
        "model_spec": asdict(DEFAULT_SPEC),
        "dtype": "float32",
        "device": "cpu",
        "q": 0,
        "day_count": "ACT/365F",
        "preprocessing": {"mean": [0, 1, 0.03, 0.2], "scale": [0.2, 0.5, 0.03, 0.1]},
        "weights_sha256": sha256_file(tmp_path / "model.pt"),
        "validation_report_sha256": sha256_file(tmp_path / "validation_report.json"),
        "validation": {"status": "baseline"},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def case():
    return (
        OptionContract(OptionType.CALL, 100, date(2027, 1, 1)),
        MarketSnapshot(date(2026, 1, 1), 100, 0.03, 0.2),
    )


def test_inference_preserves_put_call_parity_and_batch_results(artifact):
    from math import exp

    surrogate = load_artifact(artifact)
    call, market = case()
    put = replace(call, option_type=OptionType.PUT)
    calls = surrogate.price_many([(call, market), (put, market)], DEFAULT_SPEC)
    assert calls[0] - calls[1] == pytest.approx(100 - 100 * exp(-0.03))
    assert calls[0] == pytest.approx(surrogate.price(call, market, DEFAULT_SPEC), rel=1e-6)
    assert surrogate.manifest["validation"]["status"] == "baseline"


def test_inference_refuses_domain_and_model_mismatch(artifact):
    surrogate = load_artifact(artifact)
    contract, market = case()
    with pytest.raises(UnsupportedInput, match="sigma0"):
        surrogate.price(contract, replace(market, sigma0=0.8), DEFAULT_SPEC)
    with pytest.raises(UnsupportedInput, match="specification"):
        surrogate.price(contract, market, replace(DEFAULT_SPEC, rho=0.0))


def test_weights_tampering_is_detected_before_torch_loading(artifact):
    with (artifact / "model.pt").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ArtifactError, match="SHA-256 mismatch"):
        load_artifact(artifact)


def test_validation_report_tampering_is_detected(artifact):
    (artifact / "validation_report.json").write_text('{"passed":true}', encoding="utf-8")
    with pytest.raises(ArtifactError, match="report SHA-256 mismatch"):
        load_artifact(artifact)


@pytest.mark.parametrize(
    "key,value",
    [
        ("feature_order", ["sigma0", "rate", "maturity_years", "log_moneyness"]),
        ("dtype", "float64"),
        ("q", 0.01),
        ("schema_version", 999),
    ],
)
def test_incompatible_artifacts_are_rejected(artifact, key, value):
    path = artifact / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest[key] = value
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactError):
        load_artifact(artifact)


def test_preprocessing_manifest_must_match_the_hashed_weights(artifact):
    path = artifact / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["preprocessing"]["mean"][0] = 0.1
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactError, match="feature mean differs"):
        load_artifact(artifact)


def test_mutating_a_manifest_view_does_not_expand_the_loaded_model_domain(artifact):
    surrogate = load_artifact(artifact)
    manifest = surrogate.manifest
    manifest["domain"]["sigma0"][1] = 2.0
    contract, market = case()
    with pytest.raises(UnsupportedInput, match="sigma0"):
        surrogate.price(contract, replace(market, sigma0=0.8), DEFAULT_SPEC)
