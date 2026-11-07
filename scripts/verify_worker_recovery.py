"""Kill only this project's worker and verify real lease-expiry recovery.

This is an explicit disruptive integration experiment for a local demo stack.
It creates a 100-position x 100-scenario reference run, waits for claimed work,
sends SIGKILL to the worker container, restarts it in finally, and waits for the
normal dispatcher to recover expired leases. No database time is altered.
"""

import argparse
import copy
import json
import os
import subprocess
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from verify_stack import Client, Verification, compose, require


def snapshot(root, run_id):
    # Canonicalize the only interpolated SQL value; all queries are read-only.
    run_id = str(uuid.UUID(run_id))
    query = f"""
        SELECT json_build_object(
            'id', r.id, 'status', r.status, 'created_at', r.created_at,
            'completed_at', r.completed_at,
            'result_count', (SELECT count(*) FROM valuations_valuationresult v WHERE v.run_id=r.id),
            'duplicate_cells', (SELECT count(*) FROM (
                SELECT scenario_index, position_index FROM valuations_valuationresult v
                WHERE v.run_id=r.id GROUP BY scenario_index, position_index HAVING count(*) > 1
            ) duplicates),
            'chunks', (SELECT json_agg(json_build_object(
                'id', c.id, 'scenario_index', c.scenario_index, 'status', c.status,
                'attempts', c.attempts, 'lease_until', c.lease_until, 'last_error', c.last_error
            ) ORDER BY c.scenario_index) FROM valuations_runchunk c WHERE c.run_id=r.id)
        ) FROM valuations_valuationrun r WHERE r.id='{run_id}'
    """
    command = [
        "docker",
        "compose",
        "--project-name",
        "option-risk-platform",
        "--file",
        str(root / "compose.yaml"),
        "exec",
        "-T",
        "db",
        "psql",
        "--username",
        os.environ.get("POSTGRES_USER", "option_risk"),
        "--dbname",
        os.environ.get("POSTGRES_DB", "option_risk"),
        "--tuples-only",
        "--no-align",
        "--command",
        query,
    ]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=20)
    require(result.returncode == 0, "read-only PostgreSQL recovery inspection failed")
    require(bool(result.stdout.strip()), "run does not exist in the project's PostgreSQL database")
    return json.loads(result.stdout)


def workload(sample):
    payload = copy.deepcopy(sample)
    prototype = sample["positions"][0]
    base_expiry = date.fromisoformat(prototype["contract"]["expiry"])
    positions = []
    for index in range(100):
        position = copy.deepcopy(prototype)
        position["contract"]["strike"] = 80.0 + index * 0.4
        position["contract"]["expiry"] = (base_expiry + timedelta(days=index % 30)).isoformat()
        position["side"] = "long" if index % 2 == 0 else "short"
        position["quantity"] = (index % 3 + 1) * (1 if index % 2 == 0 else -1)
        positions.append(position)
    payload["positions"] = positions
    payload["scenarios"] = [{"name": "base"}] + [
        {
            "name": f"recovery-{index}",
            "spot_shock_pct": index % 21 - 10,
            "sigma0_shock_pp": index % 5,
            "rate_shock_bp": (index % 7 - 3) * 25,
        }
        for index in range(1, 100)
    ]
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=420)
    parser.add_argument("--output", type=Path, default=Path("work/worker-recovery.json"))
    args = parser.parse_args(argv)
    if not os.environ.get("DEMO_PASSWORD"):
        parser.error("DEMO_PASSWORD must be provided in the environment")
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    root = Path(__file__).resolve().parents[1]
    services = compose(root, "ps", "--services", "--status", "running").splitlines()
    require(
        all(service in services for service in ("api", "db", "worker", "dispatcher")),
        "the complete local API/database/worker/dispatcher stack must be running",
    )
    images = {
        service: compose(root, "images", "-q", service).strip()
        for service in ("api", "worker", "dispatcher")
    }
    require(len(set(images.values())) == 1, "API and workers must use the same source image")
    client = Client(args.base_url)
    client.login(os.environ.get("DEMO_USERNAME", "demo"), os.environ["DEMO_PASSWORD"])
    sample, _, _ = client.request("GET", "/api/sample/")
    checker = Verification(client, args.timeout, artifact=None)
    record, _ = checker.create_inputs(workload(sample), "worker-loss-recovery")
    accepted, _, submit_seconds = checker.submit(record, "REFERENCE")
    run_id = accepted["id"]
    started = time.perf_counter()
    before = None
    while time.perf_counter() - started < 60:
        state = snapshot(root, run_id)
        if any(chunk["status"] == "RUNNING" for chunk in state["chunks"]):
            before = state
            break
        require(
            state["status"] not in {"COMPLETED", "PARTIAL_ERROR", "FAILED"},
            "work finished before an active lease was observed; rerun the experiment",
        )
        time.sleep(0.1)
    require(before is not None, "no running chunk was observed within 60 seconds")
    killed_at = datetime.now(UTC).isoformat()
    kill_started = time.perf_counter()
    try:
        compose(root, "kill", "--signal", "SIGKILL", "worker")
        at_loss = snapshot(root, run_id)
    finally:
        compose(root, "up", "-d", "worker")
    running_ids = {chunk["id"] for chunk in at_loss["chunks"] if chunk["status"] == "RUNNING"}
    require(running_ids, "all work finished before SIGKILL; no interrupted lease to verify")
    print(
        f"Worker SIGKILL/restart completed; {len(running_ids)} claimed chunks observed. "
        "Waiting for real lease expiry and dispatcher recovery.",
        flush=True,
    )
    deadline = time.perf_counter() + args.timeout
    observations = []
    while time.perf_counter() < deadline:
        state = snapshot(root, run_id)
        entry = {
            "seconds_after_kill": time.perf_counter() - kill_started,
            "status": state["status"],
            "result_count": state["result_count"],
            "running_chunks": sum(chunk["status"] == "RUNNING" for chunk in state["chunks"]),
            "retried_chunks": sum(chunk["attempts"] > 1 for chunk in state["chunks"]),
        }
        observations.append(entry)
        print(json.dumps(entry), flush=True)
        if state["status"] in {"COMPLETED", "PARTIAL_ERROR", "FAILED"}:
            break
        time.sleep(min(20, max(0, deadline - time.perf_counter())))
    else:
        raise RuntimeError(
            "run did not recover before timeout; worker was restarted and left running"
        )
    after = state
    document, _, _ = client.request("GET", f"/api/runs/{run_id}/")
    checker.validate_totals(document)
    require(
        after["result_count"] == 10_000 and document["progress"]["total"] == 10_000,
        "recovery did not preserve the complete 100 x 100 result grid",
    )
    require(after["duplicate_cells"] == 0, "recovery produced duplicate published cells")
    require(
        all(cell["reference_price"] > 0 for cell in document["results"]),
        "positive-price test inputs produced zero placeholders",
    )
    retried = [chunk for chunk in after["chunks"] if chunk["attempts"] > 1]
    require(
        running_ids & {chunk["id"] for chunk in retried},
        "no previously claimed chunk retried; SIGKILL timing did not interrupt active work",
    )
    require(
        any(
            chunk["id"] in running_ids and "lease expired" in chunk["last_error"]
            for chunk in retried
        ),
        "retry evidence does not show recovery of an expired worker lease",
    )
    require(
        all(chunk["status"] == "COMPLETED" for chunk in after["chunks"]),
        "not all recovered chunks completed",
    )
    output = {
        "status": "passed",
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "image_ids": images,
        "killed_at_utc": killed_at,
        "submit_http_202_seconds": submit_seconds,
        "wall_seconds": time.perf_counter() - started,
        "server_created_to_completed_seconds": document["elapsed_seconds"],
        "before_kill": before,
        "after_sigkill": at_loss,
        "after_recovery": after,
        "observations": observations,
        "retried_chunks": retried,
        "provenance": document["provenance"],
        "checks": {
            "actual_sigkill": True,
            "worker_restarted": True,
            "real_lease_expiry_no_clock_change": True,
            "reference_cells": 10_000,
            "duplicate_cells": 0,
            "complete_portfolio_totals": len(document["totals"]),
            "previously_claimed_chunks_retried": len(running_ids & {c["id"] for c in retried}),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "passed",
                "run_id": run_id,
                "retried_chunks": len(retried),
                "output": str(args.output),
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
