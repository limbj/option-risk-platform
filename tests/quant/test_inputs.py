import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest

from quant.contracts import OptionType, Side
from quant.errors import ContractValidationError
from quant.inputs import parse_inputs


@pytest.fixture
def payload():
    return {
        "market": {
            "valuation_date": "2026-11-08",
            "spot": 100,
            "rate": 0.03,
            "sigma0": 0.2,
            "underlying": "SYNTH_INDEX",
            "currency": "USD",
        },
        "model": {"kappa": 2, "theta": 0.04, "xi": 0.3, "rho": -0.7},
        "positions": [
            {
                "contract": {
                    "option_type": "call",
                    "strike": 100,
                    "expiry": "2027-11-08",
                    "underlying": "SYNTH_INDEX",
                    "currency": "USD",
                },
                "side": "long",
                "quantity": 2,
                "multiplier": 100,
            },
            {
                "contract": {"option_type": "put", "strike": 95, "expiry": "2027-11-08"},
                "side": "short",
                "quantity": -1,
                "multiplier": 100,
            },
        ],
        "scenarios": [
            {"name": "base"},
            {"name": "stress", "spot_shock_pct": -10, "sigma0_shock_pp": 5, "rate_shock_bp": 100},
        ],
    }


def test_json_inputs_create_validated_immutable_financial_objects(payload):
    bundle = parse_inputs(payload)
    assert bundle.market.valuation_date == date(2026, 11, 8)
    assert bundle.market.v0 == pytest.approx(0.04)
    assert bundle.positions[0].contract.option_type is OptionType.CALL
    assert bundle.positions[1].side is Side.SHORT
    assert bundle.positions[1].quantity == -1
    assert bundle.scenarios[1].sigma0_change == pytest.approx(0.05)
    assert isinstance(bundle.positions, tuple)
    assert isinstance(bundle.scenarios, tuple)
    with pytest.raises(FrozenInstanceError):
        bundle.market = None


def test_mutating_raw_input_cannot_change_an_existing_bundle(payload):
    bundle = parse_inputs(payload)
    payload["market"]["spot"] = 1
    payload["positions"][0]["quantity"] = 999
    payload["scenarios"].clear()
    assert bundle.market.spot == 100
    assert bundle.positions[0].quantity == 2
    assert len(bundle.scenarios) == 2


def test_checked_in_sample_is_valid_and_contains_both_position_sides():
    sample_path = Path(__file__).resolve().parents[2] / "examples" / "demo_inputs.json"
    bundle = parse_inputs(json.loads(sample_path.read_text(encoding="utf-8")))
    assert {position.side for position in bundle.positions} == {Side.LONG, Side.SHORT}
    assert any(
        scenario.spot_relative_change == scenario.sigma0_change == scenario.rate_change == 0
        for scenario in bundle.scenarios
    )


@pytest.mark.parametrize("key", ["market", "model", "positions", "scenarios"])
def test_top_level_input_sections_are_required(payload, key):
    del payload[key]
    with pytest.raises(ContractValidationError):
        parse_inputs(payload)


@pytest.mark.parametrize(
    "path",
    [(), ("market",), ("model",), ("positions", 0), ("positions", 0, "contract"), ("scenarios", 0)],
)
def test_unknown_fields_are_rejected_at_every_boundary(payload, path):
    target = payload
    for key in path:
        target = target[key]
    target["unknown_input"] = 1
    with pytest.raises(ContractValidationError):
        parse_inputs(payload)


@pytest.mark.parametrize(
    ("path", "key"),
    [
        (("market",), "valuation_date"),
        (("market",), "spot"),
        (("market",), "rate"),
        (("market",), "sigma0"),
        (("model",), "kappa"),
        (("model",), "theta"),
        (("model",), "xi"),
        (("model",), "rho"),
        (("positions", 0), "contract"),
        (("positions", 0), "side"),
        (("positions", 0), "quantity"),
        (("positions", 0), "multiplier"),
        (("positions", 0, "contract"), "option_type"),
        (("positions", 0, "contract"), "strike"),
        (("positions", 0, "contract"), "expiry"),
        (("scenarios", 0), "name"),
    ],
)
def test_required_financial_fields_never_receive_silent_defaults(payload, path, key):
    target = payload
    for segment in path:
        target = target[segment]
    del target[key]
    with pytest.raises(ContractValidationError):
        parse_inputs(payload)


@pytest.mark.parametrize(
    "value",
    ["20261108", "2026-1-8", "2026-11-08T00:00:00", "2026-02-30", "2026-W45-7", 20261108, None],
)
@pytest.mark.parametrize("field", ["valuation_date", "expiry"])
def test_dates_use_strict_iso_calendar_format(payload, value, field):
    target = payload["market"] if field == "valuation_date" else payload["positions"][0]["contract"]
    target[field] = value
    with pytest.raises(ContractValidationError):
        parse_inputs(payload)


@pytest.mark.parametrize("expiry", ["2026-11-08", "2026-11-07"])
def test_input_bundle_rejects_ineligible_maturities(payload, expiry):
    payload["positions"][0]["contract"]["expiry"] = expiry
    with pytest.raises(ContractValidationError):
        parse_inputs(payload)


@pytest.mark.parametrize("value", [True, "100", None, float("nan"), float("inf")])
def test_parser_does_not_coerce_bad_numerics_into_financial_values(payload, value):
    payload["market"]["spot"] = value
    with pytest.raises(ContractValidationError):
        parse_inputs(payload)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("market", "currency", "EUR"),
        ("market", "underlying", "SPX"),
        ("market", "volatility", 20),
        ("market", "rate_pct", 3),
        ("scenario", "vol_shock", 0.05),
        ("scenario", "rate_shock", 0.01),
        ("scenario", "sigma0_shock_pp", -20),
        ("scenario", "spot_shock_pct", -100),
        ("position", "side", "BUY"),
        ("position", "quantity", -2),
        ("position", "quantity", 2.0),
        ("contract", "option_type", "CALL"),
        ("contract", "exercise", "american"),
        ("contract", "currency", "EUR"),
    ],
)
def test_input_boundary_rejects_incompatible_units_products_and_positions(
    payload, section, field, value
):
    targets = {
        "market": payload["market"],
        "scenario": payload["scenarios"][1],
        "position": payload["positions"][0],
        "contract": payload["positions"][0]["contract"],
    }
    targets[section][field] = value
    with pytest.raises(ContractValidationError):
        parse_inputs(payload)


@pytest.mark.parametrize("section", ["positions", "scenarios"])
@pytest.mark.parametrize("count", [0, 101])
def test_input_collections_enforce_the_initial_size_cap(payload, section, count):
    payload[section] = [deepcopy(payload[section][0]) for _ in range(count)]
    if section == "scenarios":
        for index, item in enumerate(payload[section]):
            item["name"] = f"scenario-{index}"
    with pytest.raises(ContractValidationError):
        parse_inputs(payload)


def test_input_cap_accepts_exactly_one_hundred_positions_and_scenarios(payload):
    payload["positions"] = [deepcopy(payload["positions"][0]) for _ in range(100)]
    payload["scenarios"] = [{"name": f"scenario-{index}"} for index in range(100)]
    bundle = parse_inputs(payload)
    assert len(bundle.positions) == len(bundle.scenarios) == 100


def test_duplicate_scenario_names_are_rejected(payload):
    payload["scenarios"][1]["name"] = payload["scenarios"][0]["name"]
    with pytest.raises(ContractValidationError):
        parse_inputs(payload)


@pytest.mark.parametrize("value", [None, [], "{}", 1])
def test_top_level_input_must_be_a_mapping(value):
    with pytest.raises(ContractValidationError):
        parse_inputs(value)


@pytest.mark.parametrize("section", ["market", "model", "positions", "scenarios"])
@pytest.mark.parametrize("value", [None, "invalid", 1])
def test_nested_input_containers_have_the_required_shape(payload, section, value):
    payload[section] = value
    with pytest.raises(ContractValidationError):
        parse_inputs(payload)
