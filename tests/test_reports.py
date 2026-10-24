"""
Automated compliance tests for the Celesto hackathon spec.

Run against a live stack:
    docker-compose up -d --wait
    python -m pytest tests/test_reports.py -v

Or against the local dev server:
    uvicorn backend.main:app --port 8080 &
    python -m pytest tests/test_reports.py -v
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path

import pytest
import httpx

ROOT = Path(__file__).parent.parent
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"
BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8080")

SANDBOX_RE = re.compile(r"^sbx-[a-z0-9]{8,}$")
ALLOWED_CAP_IDS = {
    "persistence", "snapshots", "celestofs", "browser", "published_ports",
    "network_policy", "safety_hooks", "host_mounts", "coding_agent_preset",
    "agentor_durable",
}
ALLOWED_STATES = {"created", "ready", "running", "succeeded", "failed", "deleted"}
ALLOWED_ATTACKS = {"prompt_injection_exfil", "destructive_command", "suspicious_package"}


# ---------------------------------------------------------------------------
# Report file tests
# ---------------------------------------------------------------------------

def test_problem_json():
    data = json.loads((REPORTS / "problem.json").read_text())
    assert len(data["who"]) >= 40, "who must be at least 40 characters"
    assert len(data["agent_work"]) >= 40, "agent_work must be at least 40 characters"
    assert len(data["proof_output"]) >= 20, "proof_output must be at least 20 characters"
    assert data["idea_source"] in {"idea_bank", "original"}, "idea_source must be idea_bank or original"


def test_capabilities_json():
    data = json.loads((REPORTS / "capabilities.json").read_text())
    caps = data["capabilities"]
    assert len(caps) >= 2, "Must have at least 2 capabilities"
    ids = [c["id"] for c in caps]
    assert len(ids) == len(set(ids)), "Capability IDs must be unique"
    for cap in caps:
        assert cap["id"] in ALLOWED_CAP_IDS, f"Unknown capability id: {cap['id']}"
        assert len(cap["why"]) >= 80, f"why for {cap['id']} must be >= 80 chars"
        evidence = ROOT / cap["evidence_path"]
        assert evidence.exists(), f"evidence_path does not exist: {cap['evidence_path']}"


def test_lifecycle_json():
    data = json.loads((REPORTS / "lifecycle.json").read_text())
    assert data["cleanup_on_success"] is True
    assert data["cleanup_on_failure"] is True
    assert data["cleanup_on_interrupt"] is True
    names = data["sandbox_names"]
    assert len(names) >= 1
    for n in names:
        assert SANDBOX_RE.match(n), f"Invalid sandbox name: {n}"
    assert len(names) == len(set(names)), "Sandbox names must be unique"

    # Each name must appear in commands.jsonl or reliability.json
    cmd_text = (LOGS / "commands.jsonl").read_text()
    rel_text = (REPORTS / "reliability.json").read_text()
    for n in names:
        assert n in cmd_text or n in rel_text, f"{n} not found in commands.jsonl or reliability.json"


def test_reliability_json():
    data = json.loads((REPORTS / "reliability.json").read_text())
    runs = data["runs"]
    n = len(runs)
    assert n >= 20, "Must have at least 20 runs"
    assert data["run_count"] == n

    # Unique names
    names = [r["sandbox_name"] for r in runs]
    assert len(names) == len(set(names)), "sandbox_names must be unique"
    for name in names:
        assert SANDBOX_RE.match(name), f"Invalid sandbox name: {name}"

    # All fresh=true
    assert all(r["fresh"] is True for r in runs)

    # Recompute statistics
    successes = sum(1 for r in runs if r["success"])
    rate = successes / n
    assert abs(data["success_rate"] - rate) <= 0.001, "success_rate mismatch"

    wc = sorted(r["wall_clock_s"] for r in runs)
    # Median: mean of n//2-th and (n//2+1)-th (1-based), i.e. indices n//2-1 and n//2 (0-based)
    median_wc = (wc[n // 2 - 1] + wc[n // 2]) / 2
    assert abs(data["median_wall_clock_s"] - median_wc) <= 0.001, "median_wall_clock_s mismatch"

    # p90: 1-based rank ceil(0.9 * n), so 0-based index ceil(0.9*n)-1
    p90_idx = math.ceil(0.9 * n) - 1
    assert abs(data["p90_wall_clock_s"] - wc[p90_idx]) <= 0.001, "p90_wall_clock_s mismatch"

    bt = sorted(r["boot_to_ready_s"] for r in runs)
    median_bt = (bt[n // 2 - 1] + bt[n // 2]) / 2
    assert abs(data["median_boot_to_ready_s"] - median_bt) <= 0.001, "median_boot_to_ready_s mismatch"

    total = sum(r["cost_usd"] for r in runs)
    assert abs(data["total_cost_usd"] - total) <= 0.01, "total_cost_usd mismatch"

    # Postmortem
    pm_path = ROOT / data["postmortem_path"]
    assert pm_path.exists(), "postmortem file does not exist"
    assert len(pm_path.read_text()) >= 200, "postmortem must be at least 200 characters"


def test_containment_json():
    data = json.loads((REPORTS / "containment.json").read_text())
    assert data["attack"] in ALLOWED_ATTACKS
    assert data["blocked"] is True
    assert data["host_untouched"] is True
    for ep in data["evidence_paths"]:
        assert (ROOT / ep).exists(), f"evidence_path does not exist: {ep}"


def test_failure_policy_json():
    data = json.loads((REPORTS / "failure_policy.json").read_text())
    assert data["failed_step"] == 7
    assert data["total_steps"] == 10
    assert data["policy"] in {"resume", "rollback", "fresh"}
    assert len(data["rationale"]) >= 200, "rationale must be >= 200 chars"

    trace_path = ROOT / data["trace_path"]
    assert trace_path.exists()
    found = False
    for line in trace_path.read_text().splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("event") == "policy_applied" and obj.get("policy") == data["policy"]:
            found = True
    assert found, "No policy_applied event found in failure_trace.jsonl"


def test_concurrency_json():
    data = json.loads((REPORTS / "concurrency.json").read_text())
    jobs = data["jobs"]
    assert len(jobs) >= 5
    names = [j["sandbox_name"] for j in jobs]
    assert len(names) == len(set(names)), "Job sandbox_names must be unique"
    for j in jobs:
        assert SANDBOX_RE.match(j["sandbox_name"])
        assert j["started_at"], "started_at must be non-empty"
    assert len(data["breakage_notes"]) >= 40


def test_commands_jsonl():
    lines = [
        ln for ln in (LOGS / "commands.jsonl").read_text().splitlines()
        if ln.strip()
    ]
    assert len(lines) >= 1

    for i, line in enumerate(lines):
        obj = json.loads(line)
        assert "ts" in obj, f"line {i}: missing ts"
        assert "sandbox_name" in obj, f"line {i}: missing sandbox_name"
        assert SANDBOX_RE.match(obj["sandbox_name"]), f"line {i}: bad sandbox_name"
        assert obj.get("command"), f"line {i}: empty command"
        assert obj.get("decision") in {"allow", "block"}, f"line {i}: bad decision"
        assert obj["execution_target"] == "celesto_sandbox", \
            f"line {i}: execution_target must be celesto_sandbox"


# ---------------------------------------------------------------------------
# HTTP endpoint tests (requires running server)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client():
    return httpx.Client(base_url=BASE_URL, timeout=10)


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_runs_contains_seed(client):
    r = client.get("/api/runs")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    names = [row["sandbox_name"] for row in data]
    assert "sbx-seeddemo1" in names, f"sbx-seeddemo1 not found in /api/runs: {names}"


def test_post_run_valid(client):
    payload = {
        "run_id": f"test-compliance-{os.getpid()}",
        "sandbox_name": "sbx-testvalid01",
        "problem_id": "compliance-check",
        "state": "created",
        "execution_target": "celesto_sandbox",
    }
    r = client.post("/api/runs", json=payload)
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["sandbox_name"] == "sbx-testvalid01"
    assert body["execution_target"] == "celesto_sandbox"


def test_post_run_bad_execution_target(client):
    payload = {
        "run_id": f"test-bad-target-{os.getpid()}",
        "sandbox_name": "sbx-testbad0001",
        "problem_id": "compliance-check",
        "state": "created",
        "execution_target": "host",
    }
    r = client.post("/api/runs", json=payload)
    assert r.status_code in {400, 422}, \
        f"Expected 400 or 422 for bad execution_target, got {r.status_code}"
