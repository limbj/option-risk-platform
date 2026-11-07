"""Reports only expose complete like-for-like totals and stress P&L."""

import math


def input_document(record):
    from apps.valuations.services import version_ids

    return {
        "id": str(record.pk),
        "name": record.name,
        "inputs": record.payload,
        "hash": record.hash,
        "version_ids": version_ids(record),
        "created_at": record.created_at.isoformat(),
    }


def run_summary(run):
    completed = run.results.count()
    failed = run.results.filter(status="FAILED").count()
    total = len(run.provenance["execution_scenarios"]) * len(run.inputs.payload["positions"])
    return {
        "id": str(run.pk),
        "input_id": str(run.inputs_id),
        "input_name": run.inputs.name,
        "mode": run.mode,
        "status": run.status,
        "progress": {"completed": completed, "total": total, "failed": failed},
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _total(cells, field, expected):
    if len(cells) != expected or any(cell[field] is None for cell in cells):
        return None
    try:
        total = math.fsum(cell[field] for cell in cells)
    except (OverflowError, ValueError):
        return None
    return total if math.isfinite(total) else None


def _difference(stressed, base):
    if stressed is None or base is None:
        return None
    value = stressed - base
    return value if math.isfinite(value) else None


def run_document(run):
    result = run_summary(run)
    scenarios = run.provenance["execution_scenarios"]
    cells = []
    for row in run.results.order_by("scenario_index", "position_index"):
        cells.append(
            {
                "scenario_index": row.scenario_index,
                "scenario_name": scenarios[row.scenario_index]["name"],
                "position_index": row.position_index,
                "status": row.status,
                "reference_price": row.reference_price,
                "reference_value": row.reference_value,
                "error": row.error or None,
                "sensitivities": row.sensitivities,
                "ml_price": row.ml_price,
                "ml_value": row.ml_value,
                "ml_error": row.ml_error or None,
                "timings": row.timings,
                "price_error": _difference(row.ml_price, row.reference_price),
            }
        )
    expected = len(run.inputs.payload["positions"])
    totals = []
    for index, scenario in enumerate(scenarios):
        scenario_cells = [cell for cell in cells if cell["scenario_index"] == index]
        value = _total(scenario_cells, "reference_value", expected)
        ml_value = _total(scenario_cells, "ml_value", expected) if run.mode == "COMPARE" else None
        totals.append(
            {
                "scenario_index": index,
                "scenario_name": scenario["name"],
                "complete": value is not None,
                "value": value,
                "pnl": None,
                "ml_complete": ml_value is not None,
                "ml_value": ml_value,
                "ml_pnl": None,
            }
        )
    base = totals[run.provenance["base_scenario_index"]]
    for total in totals:
        total["pnl"] = _difference(total["value"], base["value"])
        total["ml_pnl"] = _difference(total["ml_value"], base["ml_value"])
        total["pnl_error"] = _difference(total["ml_pnl"], total["pnl"])
    result.update(
        pinned_inputs=run.inputs.payload,
        provenance=run.provenance,
        results=cells,
        totals=totals,
        elapsed_seconds=(run.completed_at - run.created_at).total_seconds()
        if run.completed_at
        else None,
    )
    return result
