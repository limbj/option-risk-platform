"""Exercise the real HTTP/PostgreSQL/outbox/Celery stack using only Python stdlib.

Run with DEMO_PASSWORD in the environment; never place passwords on the command
line. No container lifecycle changes occur unless --recovery-dispatcher is set.
"""

import argparse
import copy
import csv
import io
import json
import math
import os
import subprocess
import time
import uuid
from datetime import UTC, date, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def close(actual, expected, message, *, rel=1e-9, absolute=1e-8):
    require(math.isfinite(actual) and math.isfinite(expected), f"{message}: non-finite value")
    require(
        math.isclose(actual, expected, rel_tol=rel, abs_tol=absolute),
        f"{message}: {actual} != {expected}",
    )


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.csrf = None

    def request(self, method, path, data=None, *, expected=200, csrf=True, raw=False):
        headers = {"Accept": "application/json", "Referer": self.base + "/"}
        if csrf and self.csrf:
            headers["X-CSRFToken"] = self.csrf
        body = None
        if data is not None:
            body = json.dumps(data, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        started = time.perf_counter()
        try:
            response = self.opener.open(
                Request(self.base + path, body, headers, method=method), timeout=20
            )
        except HTTPError as exc:
            response = exc
        with response:
            content = response.read().decode("utf-8")
            status = response.status
            response_headers = dict(response.headers)
        seconds = time.perf_counter() - started
        require(status == expected, f"{method} {path}: expected HTTP {expected}, received {status}")
        result = content if raw else json.loads(content)
        return result, seconds, response_headers

    def login(self, username, password):
        session, _, _ = self.request("GET", "/api/session/")
        self.csrf = session["csrfToken"]
        session, _, _ = self.request(
            "POST", "/api/login/", {"username": username, "password": password}
        )
        require(session["authenticated"], "login did not create an authenticated session")
        self.csrf = session["csrfToken"]


class Verification:
    def __init__(self, client, timeout, artifact):
        self.client, self.timeout, self.artifact = client, timeout, artifact
        self.checks = []
        self.runs = []
        self.submitted_at = {}

    def mark(self, name, **details):
        self.checks.append({"name": name, "passed": True, **details})
        print(f"PASS {name}", flush=True)

    def create_inputs(self, payload, label):
        record, seconds, _ = self.client.request(
            "POST",
            "/api/inputs/",
            {"name": f"stack-check-{label}-{uuid.uuid4().hex[:8]}", "inputs": payload},
            expected=201,
        )
        require(
            set(record["version_ids"]) == {"portfolio", "market", "scenarios", "model"},
            "input version does not pin all component IDs",
        )
        require(len(record["hash"]) == 64, "input snapshot hash is missing")
        return record, seconds

    def submit(self, record, mode, *, key=None):
        request = {
            "input_id": record["id"],
            "mode": mode,
            "idempotency_key": key or "stack-" + uuid.uuid4().hex,
        }
        if mode == "COMPARE":
            request["artifact_id"] = self.artifact["id"]
        submitted_at = time.perf_counter()
        accepted, seconds, _ = self.client.request("POST", "/api/runs/", request, expected=202)
        require(accepted["created"], "a unique request did not create a durable run")
        self.submitted_at[accepted["id"]] = submitted_at
        return accepted, request, seconds

    def wait(self, run_id):
        started = time.perf_counter()
        statuses = []
        while time.perf_counter() - started < self.timeout:
            document, _, _ = self.client.request("GET", f"/api/runs/{run_id}/")
            if not statuses or statuses[-1] != document["status"]:
                statuses.append(document["status"])
            if document["status"] in {"COMPLETED", "PARTIAL_ERROR", "FAILED"}:
                return document, time.perf_counter() - started, statuses
            time.sleep(0.25)
        raise VerificationError(f"run {run_id} did not finish within {self.timeout:g} seconds")

    def run(self, record, mode, label):
        accepted, _, submit_seconds = self.submit(record, mode)
        document, wait_seconds, statuses = self.wait(accepted["id"])
        self.record_run(document, label, submit_seconds, wait_seconds, statuses)
        return document

    def record_run(self, document, label, submit_seconds, wait_seconds, statuses):
        self.runs.append(
            {
                "label": label,
                "id": document["id"],
                "mode": document["mode"],
                "status": document["status"],
                "observed_statuses": statuses,
                "submit_http_202_seconds": submit_seconds,
                "submit_and_poll_wall_seconds": (
                    time.perf_counter() - self.submitted_at[document["id"]]
                    if document["id"] in self.submitted_at
                    else submit_seconds + wait_seconds
                ),
                "server_created_to_completed_seconds": document["elapsed_seconds"],
                "progress": document["progress"],
                "cell_timings": [cell["timings"] for cell in document["results"]],
                "totals": document["totals"],
                "provenance": document["provenance"],
            }
        )

    def validate_totals(self, document, *, ml_expected=None):
        require(document["status"] == "COMPLETED", f"reference run status {document['status']}")
        require(document["progress"]["failed"] == 0, "reference contains failed cells")
        require(
            document["progress"]["completed"] == document["progress"]["total"],
            "progress does not count all required cells",
        )
        positions = document["pinned_inputs"]["positions"]
        cells = document["results"]
        require(
            len({(c["scenario_index"], c["position_index"]) for c in cells}) == len(cells),
            "duplicate scenario-position result cells",
        )
        for cell in cells:
            position = positions[cell["position_index"]]
            close(
                cell["reference_value"],
                position["quantity"] * position["multiplier"] * cell["reference_price"],
                "signed quantity/multiplier valuation",
            )
            require(cell["error"] is None, "completed reference cell has an error")
            if cell["scenario_index"] == document["provenance"]["base_scenario_index"]:
                risk = cell["sensitivities"]
                require(isinstance(risk, dict), "base reference sensitivities are missing")
                for key in ("delta", "gamma", "initial_volatility_sensitivity"):
                    require(math.isfinite(risk[key]), f"non-finite reference {key}")
                close(risk["sigma0_bump"], 0.0001, "initial-volatility sensitivity bump units")
            if ml_expected is True:
                require(
                    cell["ml_price"] is not None and cell["ml_error"] is None,
                    "supported comparison has a missing ML price",
                )
                close(
                    cell["ml_value"],
                    position["quantity"] * position["multiplier"] * cell["ml_price"],
                    "ML signed quantity/multiplier valuation",
                )
                close(
                    cell["price_error"],
                    cell["ml_price"] - cell["reference_price"],
                    "price error sign",
                )
            elif ml_expected is False:
                require(
                    cell["ml_price"] is None and bool(cell["ml_error"]),
                    "unsupported ML value was fabricated or lacks a reason",
                )
        base = document["totals"][document["provenance"]["base_scenario_index"]]
        for total in document["totals"]:
            rows = [c for c in cells if c["scenario_index"] == total["scenario_index"]]
            require(len(rows) == len(positions) and total["complete"], "incomplete reference total")
            close(total["value"], math.fsum(c["reference_value"] for c in rows), "portfolio total")
            close(total["pnl"], total["value"] - base["value"], "stress P&L sign")
            if ml_expected is True:
                require(total["ml_complete"], "supported ML portfolio is incomplete")
                close(total["ml_value"], math.fsum(c["ml_value"] for c in rows), "ML total")
                close(total["ml_pnl"], total["ml_value"] - base["ml_value"], "ML stress P&L")
            elif ml_expected is False:
                require(
                    total["ml_value"] is None
                    and total["ml_pnl"] is None
                    and not total["ml_complete"],
                    "unsupported ML total/P&L must be null",
                )
        require(
            document["provenance"]["authoritative_engine"] == "reference",
            "reference authority lost",
        )
        require(document["provenance"]["day_count"] == "ACT/365F", "day count changed")


def check_invalid_inputs(checker, sample):
    mutations = [
        ("boolean spot", ("market", "spot"), True),
        ("unknown volatility units", ("market", "volatility_pct"), 20),
        ("wrong quantity sign", ("positions", 0, "quantity"), -10),
        (
            "same-day maturity",
            ("positions", 0, "contract", "expiry"),
            sample["market"]["valuation_date"],
        ),
        ("invalid spot shock", ("scenarios", 1, "spot_shock_pct"), -100),
        ("invalid volatility shock", ("scenarios", 1, "sigma0_shock_pp"), -20),
    ]
    for name, path, value in mutations:
        payload = copy.deepcopy(sample)
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        checker.client.request(
            "POST", "/api/inputs/", {"name": "invalid", "inputs": payload}, expected=400
        )
        checker.mark(f"invalid input rejected: {name}")


def check_exports(checker, document):
    run_id = document["id"]
    exported, _, headers = checker.client.request("GET", f"/api/runs/{run_id}/export/?format=json")
    require(exported == document, "JSON export differs from completed report")
    require("attachment" in headers.get("Content-Disposition", ""), "export is not downloadable")
    raw, _, _ = checker.client.request("GET", f"/api/runs/{run_id}/export/?format=csv", raw=True)
    rows = list(csv.DictReader(io.StringIO(raw)))
    require(len(rows) == len(document["results"]), "CSV cell count differs from report")
    for row in rows:
        require(row["run_id"] == run_id, "CSV run identifier mismatch")
        require(json.loads(row["provenance"]) == document["provenance"], "CSV provenance mismatch")
        require(row["scenario_complete"] == "True", "CSV completeness is missing")
        require(row["reference_price"] != "", "CSV reference price is missing")
    checker.client.request("GET", f"/api/runs/{run_id}/export/?format=xml", expected=400)
    checker.mark("JSON/CSV exports preserve cells, provenance and completeness")


def check_parity(checker, sample):
    payload = copy.deepcopy(sample)
    call = copy.deepcopy(payload["positions"][0])
    call["quantity"], call["side"] = 1, "long"
    put = copy.deepcopy(call)
    put["contract"]["option_type"], put["quantity"], put["side"] = "put", -1, "short"
    payload["positions"] = [call, put]
    payload["scenarios"].append({"name": "volatility-only", "sigma0_shock_pp": 5})
    record, _ = checker.create_inputs(payload, "parity")
    document = checker.run(record, "COMPARE", "parity-and-stress-units")
    checker.validate_totals(document, ml_expected=True)
    market = payload["market"]
    maturity = (
        date.fromisoformat(call["contract"]["expiry"])
        - date.fromisoformat(market["valuation_date"])
    ).days / 365
    for index, scenario in enumerate(document["provenance"]["execution_scenarios"]):
        spot = market["spot"] * (1 + scenario["spot_shock_pct"] / 100)
        rate = market["rate"] + scenario["rate_shock_bp"] / 10_000
        expected = spot - call["contract"]["strike"] * math.exp(-rate * maturity)
        rows = [cell for cell in document["results"] if cell["scenario_index"] == index]
        close(
            rows[0]["reference_price"] - rows[1]["reference_price"],
            expected,
            "reference put-call parity and explicit stress units",
            absolute=1e-7,
        )
        close(
            rows[0]["ml_price"] - rows[1]["ml_price"],
            expected,
            "ML put-call parity and explicit stress units",
            absolute=1e-6,
        )
    checker.mark("reference/ML parity, ACT/365F, instantaneous spot percent/rate bp/vol points")


def compose(root, *arguments):
    command = [
        "docker",
        "compose",
        "--project-name",
        "option-risk-platform",
        "--file",
        str(root / "compose.yaml"),
        *arguments,
    ]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60)
    require(result.returncode == 0, f"project Compose command failed: {' '.join(arguments)}")
    return result.stdout


def dispatcher_recovery(checker, record):
    root = Path(__file__).resolve().parents[1]
    running = compose(root, "ps", "--services", "--status", "running").splitlines()
    require(
        "dispatcher" in running and "worker" in running,
        "recovery test requires this project's running dispatcher and worker",
    )
    compose(root, "stop", "dispatcher")
    try:
        accepted, _, submit_seconds = checker.submit(record, "REFERENCE")
        time.sleep(1)
        queued, _, _ = checker.client.request("GET", f"/api/runs/{accepted['id']}/")
        require(
            queued["status"] == "QUEUED" and queued["results"] == [],
            "new run should remain durable and queued while dispatcher is down",
        )
        require(
            all(total["value"] is None and total["pnl"] is None for total in queued["totals"]),
            "unfinished totals were replaced with zero",
        )
    finally:
        compose(root, "start", "dispatcher")
    document, wait_seconds, statuses = checker.wait(accepted["id"])
    checker.validate_totals(document)
    checker.record_run(
        document, "dispatcher-outage-recovery", submit_seconds, wait_seconds, ["QUEUED"] + statuses
    )
    checker.mark("dispatcher restart recovers durable queued work; pending totals stay null")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--output", type=Path, default=Path("work/stack-validation.json"))
    parser.add_argument(
        "--recovery-dispatcher",
        action="store_true",
        help="Temporarily stop/restart only this project's dispatcher",
    )
    args = parser.parse_args(argv)
    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        parser.error("DEMO_PASSWORD must be set in the environment")
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    started = time.perf_counter()
    client = Client(args.base_url)
    client.request("GET", "/api/health/")
    client.request("GET", "/api/inputs/", expected=403)
    client.request(
        "POST",
        "/api/login/",
        {"username": "invalid", "password": "invalid"},
        csrf=False,
        expected=403,
        raw=True,
    )
    client.login(os.environ.get("DEMO_USERNAME", "demo"), password)
    artifacts, _, _ = client.request("GET", "/api/models/")
    require(bool(artifacts["items"]), "register an ML artifact before running stack verification")
    artifact = next(
        (
            item
            for item in artifacts["items"]
            if item["manifest"].get("validation", {}).get("status") == "passed"
        ),
        artifacts["items"][0],
    )
    checker = Verification(client, args.timeout, artifact)
    checker.mark("real session login, unauthenticated resource rejection and login CSRF")
    sample, _, _ = client.request("GET", "/api/sample/")
    client.request(
        "POST", "/api/inputs/", {"name": "invalid", "inputs": sample}, csrf=False, expected=403
    )
    checker.mark("authenticated write without CSRF is rejected")
    check_invalid_inputs(checker, sample)
    record, input_seconds = checker.create_inputs(sample, "sample")
    for method in ("PUT", "PATCH", "DELETE"):
        client.request(method, f"/api/inputs/{record['id']}/", {}, expected=405)
    retrieved, _, _ = client.request("GET", f"/api/inputs/{record['id']}/")
    require(retrieved == record, "published inputs changed after rejected writes")
    checker.mark("immutable input version and component IDs", create_http_seconds=input_seconds)

    accepted, request, submit_seconds = checker.submit(record, "REFERENCE")
    repeated, _, _ = client.request("POST", "/api/runs/", request, expected=202)
    require(
        repeated["id"] == accepted["id"] and not repeated["created"],
        "idempotent POST created a new run",
    )
    client.request("POST", "/api/runs/", request | {"mode": "COMPARE"}, expected=409)
    reference, wait_seconds, statuses = checker.wait(accepted["id"])
    checker.record_run(reference, "reference", submit_seconds, wait_seconds, statuses)
    checker.validate_totals(reference)
    checker.mark("durable 202, idempotent replay and conflicting key rejection")
    checker.mark("reference valuation, signed positions, complete totals and stress P&L")
    compared = checker.run(record, "COMPARE", "compare")
    checker.validate_totals(compared, ml_expected=True)
    for first, second in zip(reference["results"], compared["results"], strict=True):
        close(
            first["reference_price"],
            second["reference_price"],
            "COMPARE must preserve reference valuation",
        )
    require(
        compared["provenance"]["artifact_manifest_hash"] == artifact["hash"],
        "artifact is not pinned",
    )
    checker.mark("COMPARE preserves reference values and pins the artifact")
    check_exports(checker, compared)
    retried, retry_seconds, _ = client.request(
        "POST", f"/api/runs/{reference['id']}/retry/", {}, expected=202
    )
    require(retried["id"] != reference["id"], "retry overwrote the original run")
    rerun, wait_seconds, statuses = checker.wait(retried["id"])
    checker.record_run(rerun, "rerun", retry_seconds, wait_seconds, statuses)
    checker.validate_totals(rerun)
    for first, second in zip(reference["results"], rerun["results"], strict=True):
        close(first["reference_price"], second["reference_price"], "rerun reproducibility")
    original, _, _ = client.request("GET", f"/api/runs/{reference['id']}/")
    require(original == reference, "rerun mutated the original result")
    checker.mark("rerun preserves original results and reproduces reference prices")
    check_parity(checker, sample)

    unsupported = copy.deepcopy(sample)
    unsupported["market"]["sigma0"] = 0.8
    out_of_domain, _ = checker.create_inputs(unsupported, "unsupported")
    rejected_ml = checker.run(out_of_domain, "COMPARE", "unsupported-ML-reference-retained")
    checker.validate_totals(rejected_ml, ml_expected=False)
    checker.mark("unsupported ML retains reference prices and null ML totals with reasons")

    second_username = os.environ.get("STACK_SECOND_USERNAME")
    second_password = os.environ.get("STACK_SECOND_PASSWORD")
    ownership = "not_run_no_second_account_credentials"
    if second_username and second_password:
        other = Client(args.base_url)
        other.login(second_username, second_password)
        other.request("GET", f"/api/inputs/{record['id']}/", expected=404)
        for suffix in ("", "export/?format=json"):
            other.request("GET", f"/api/runs/{reference['id']}/{suffix}", expected=404)
        other.request(
            "POST", "/api/runs/", request | {"idempotency_key": uuid.uuid4().hex}, expected=404
        )
        other.request("POST", f"/api/runs/{reference['id']}/retry/", {}, expected=404)
        checker.mark(
            "second owner cannot read, execute, export or retry another owner's inputs/results"
        )
        ownership = "passed"
    if args.recovery_dispatcher:
        dispatcher_recovery(checker, record)
    client.request("POST", "/api/logout/", {})
    client.request("GET", "/api/inputs/", expected=403)
    checker.mark("logout invalidates resource access")
    report = {
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "status": "passed",
        "duration_seconds": time.perf_counter() - started,
        "checks": checker.checks,
        "runs": checker.runs,
        "ownership": ownership,
        "dispatcher_recovery": "passed" if args.recovery_dispatcher else "not_run",
        "worker_loss_recovery": "not_run_by_this_script",
        "timing_scope": "HTTP POST latency, polling wall time and server duration are separate. "
        "Worker cell timing excludes queue/API and may include sensitivities. "
        "These small workload samples are not a throughput benchmark.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "passed",
                "checks": len(checker.checks),
                "runs": len(checker.runs),
                "output": str(args.output),
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
