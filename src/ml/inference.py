"""CPU-only artifact loading and explicitly bounded comparison inference."""

import hashlib
import json
import pickle
from copy import deepcopy
from dataclasses import asdict
from math import exp, isfinite
from pathlib import Path

import torch

from ml.features import (
    FEATURE_ORDER,
    UnsupportedInput,
    features,
    validate_features,
    validate_spec,
)
from ml.network import ARCHITECTURE, PricingMLP
from quant.contracts import HestonModelSpec, MarketSnapshot, OptionContract, OptionType


class ArtifactError(ValueError):
    """The artifact is corrupt or incompatible with this inference implementation."""


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Surrogate:
    def __init__(self, network: PricingMLP, manifest: dict):
        # Tiny CPU MLPs otherwise incur severe inter-thread overhead. The
        # explicit artifact runtime owns this setting, never package import.
        torch.set_num_threads(1)
        self.network = network.eval()
        self._manifest = deepcopy(manifest)

    @property
    def manifest(self) -> dict:
        return deepcopy(self._manifest)

    def price_many(
        self,
        cases: list[tuple[OptionContract, MarketSnapshot]],
        spec: HestonModelSpec,
    ) -> list[float]:
        validate_spec(spec, self._manifest["model_spec"])
        if not cases:
            return []
        rows = [features(contract, market) for contract, market in cases]
        for row in rows:
            validate_features(row, self._manifest["domain"])
        with torch.inference_mode():
            normalized = self.network(torch.tensor(rows, dtype=torch.float32)).tolist()
        result = []
        for value, row, (contract, market) in zip(normalized, rows, cases, strict=True):
            call = value * contract.strike
            parity = market.spot - contract.strike * exp(-market.rate * row[1])
            price = call if contract.option_type is OptionType.CALL else call - parity
            lower = max(0.0, parity if contract.option_type is OptionType.CALL else -parity)
            upper = (
                market.spot
                if contract.option_type is OptionType.CALL
                else contract.strike * exp(-market.rate * row[1])
            )
            # Float32 can violate strict double-precision bounds by a few ulps;
            # such cells are marked unsupported rather than replaced or clamped.
            if not isfinite(price) or price < lower or price > upper:
                raise UnsupportedInput("surrogate output violates financial price bounds")
            result.append(price)
        return result

    def price(
        self, contract: OptionContract, market: MarketSnapshot, spec: HestonModelSpec
    ) -> float:
        return self.price_many([(contract, market)], spec)[0]


def load_artifact(directory: str | Path) -> Surrogate:
    """Load fixed filenames, verify weights SHA-256, and use restricted torch loading.

    Artifacts are local operator-generated files, never user-uploaded pickle
    objects. Failed quality gates still allow clearly labelled COMPARE mode.
    """
    directory = Path(directory)
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["schema_version"] != 1:
            raise ArtifactError("unsupported artifact schema")
        if manifest["feature_order"] != FEATURE_ORDER or manifest["architecture"] != ARCHITECTURE:
            raise ArtifactError("unsupported feature order or architecture")
        if manifest["dtype"] != "float32" or manifest["device"] != "cpu":
            raise ArtifactError("only CPU float32 artifacts are supported")
        if manifest["q"] != 0 or manifest["day_count"] != "ACT/365F":
            raise ArtifactError("unsupported pricing conventions")
        spec = HestonModelSpec(**manifest["model_spec"])
        if asdict(spec) != manifest["model_spec"]:
            raise ArtifactError("invalid model specification")
        for name in FEATURE_ORDER:
            low, high = manifest["domain"][name]
            if not all(type(x) in (int, float) and isfinite(x) for x in (low, high)) or low >= high:
                raise ArtifactError("invalid feature domain")
        mean, scale = manifest["preprocessing"]["mean"], manifest["preprocessing"]["scale"]
        if len(mean) != 4 or len(scale) != 4:
            raise ArtifactError("invalid preprocessing vector lengths")
        if not all(type(x) in (int, float) and isfinite(x) for x in [*mean, *scale]):
            raise ArtifactError("preprocessing values must be finite")
        if any(x <= 0 for x in scale):
            raise ArtifactError("preprocessing scales must be positive")
        weights = directory / "model.pt"
        if sha256_file(weights) != manifest["weights_sha256"]:
            raise ArtifactError("weights SHA-256 mismatch")
        if (
            sha256_file(directory / "validation_report.json")
            != manifest["validation_report_sha256"]
        ):
            raise ArtifactError("validation report SHA-256 mismatch")
        network = PricingMLP(mean, scale)
        state = torch.load(weights, map_location="cpu", weights_only=True)
        network.load_state_dict(state, strict=True)
        if not all(torch.isfinite(tensor).all().item() for tensor in state.values()):
            raise ArtifactError("weights contain non-finite values")
        if not torch.equal(network.feature_mean, torch.tensor(mean, dtype=torch.float32)):
            raise ArtifactError("stored feature mean differs from manifest")
        if not torch.equal(network.feature_scale, torch.tensor(scale, dtype=torch.float32)):
            raise ArtifactError("stored feature scale differs from manifest")
        return Surrogate(network, manifest)
    except ArtifactError:
        raise
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        pickle.UnpicklingError,
        EOFError,
    ) as exc:
        raise ArtifactError(f"invalid artifact: {exc}") from exc
