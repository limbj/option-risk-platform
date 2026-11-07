"""Seeded Heston teacher data with a parameter region excluded from training."""

import hashlib
from datetime import date, timedelta
from math import exp

import numpy as np

from ml.features import DOMAIN, FEATURE_ORDER, HELDOUT_REGION, in_heldout_region
from quant.contracts import MarketSnapshot, OptionContract, OptionType
from quant.errors import PricingError


def case_from_features(row, option_type=OptionType.CALL):
    x, maturity, rate, sigma0 = (float(value) for value in row)
    valuation_date = date(2026, 11, 8)
    days = round(maturity * 365)
    return (
        OptionContract(option_type, 100.0, valuation_date + timedelta(days=days)),
        MarketSnapshot(valuation_date, 100.0 * exp(x), rate, sigma0),
    )


def sample_features(count: int, rng, *, heldout: bool = False) -> np.ndarray:
    rows = []
    while len(rows) < count:
        row = [float(rng.uniform(*DOMAIN[name])) for name in FEATURE_ORDER]
        if heldout:
            for name, bounds in HELDOUT_REGION.items():
                row[FEATURE_ORDER.index(name)] = float(rng.uniform(*bounds))
        row[1] = round(row[1] * 365) / 365
        if in_heldout_region(row) == heldout:
            rows.append(row)
    return np.asarray(rows, dtype=np.float64).reshape(-1, 4)


def edge_features(count: int, rng) -> np.ndarray:
    rows = sample_features(count, rng)
    for index, row in enumerate(rows):
        axis = index % 4
        row[axis] = DOMAIN[FEATURE_ORDER[axis]][(index // 4) % 2]
    return rows


def labels(pricer, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    valid_rows, values, failures = [], [], []
    for row in rows:
        try:
            value = pricer.price(*case_from_features(row)) / 100.0
        except PricingError as exc:
            failures.append({"features": row.tolist(), "reason": str(exc)})
        else:
            valid_rows.append(row)
            values.append(value)
    if not valid_rows:
        raise ValueError("teacher produced no valid labels for this split")
    return np.asarray(valid_rows), np.asarray(values), failures


def dataset_hash(arrays: dict[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for key in sorted(arrays):
        values = np.ascontiguousarray(arrays[key], dtype="<f8")
        digest.update(key.encode("ascii"))
        digest.update(str(values.shape).encode("ascii"))
        digest.update(values.tobytes())
    return digest.hexdigest()


def generate_dataset(pricer, samples: int, seed: int) -> tuple[dict[str, np.ndarray], dict]:
    rng = np.random.default_rng(seed)
    counts = {
        "train": samples,
        "tune": max(128, samples // 10),
        "random": max(256, samples // 10),
        "heldout": max(256, samples // 10),
        "edge": max(256, samples // 10),
    }
    arrays = {}
    failures = {}
    for split, count in counts.items():
        rows = (
            edge_features(count, rng)
            if split == "edge"
            else sample_features(count, rng, heldout=split == "heldout")
        )
        valid_rows, values, failures[split] = labels(pricer, rows)
        arrays[f"{split}_x"] = valid_rows
        arrays[f"{split}_y"] = values
    return arrays, failures
