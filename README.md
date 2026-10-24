# PatchArena

> AI-generated patches shouldn't be trusted blindly. Let them compete, test them, and choose a winner based on evidence.

**Repository:** [https://github.com/23A91A4418/patcharena](https://github.com/23A91A4418/patcharena)

---

## Problem statement

Software engineering teams and open-source maintainers receive bug reports and need AI-generated fix candidates evaluated objectively before anything is merged. Without a safe execution environment, running LLM-generated code patches on the host machine risks destructive side-effects, secret leakage, or supply-chain attacks from hallucinated dependencies. PatchArena solves this by running every candidate patch inside an isolated Celesto microVM sandbox: the agent clones the repo, installs dependencies, applies the patch, runs the test suite, starts the preview app, and captures evidence — all without touching the host machine. The deterministic judge ranks results by test pass rate, diff size, and preview availability.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                      Operator / Browser                         │
│           HTTP / SSE  ←→  FastAPI Backend (port 8080)           │
│           POST /api/arena/runs  ·  GET /api/runs                │
│           GET /health  ·  SSE /api/replay/{id}/events           │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│              Run Ledger API  (backend/main.py)                   │
│   - POST /api/runs  →  validates & stores row in Postgres       │
│   - GET  /api/runs  →  queries Postgres run ledger              │
│   - POST /api/arena/runs  →  starts arena orchestrator          │
│                                                                  │
│              Postgres Ledger  (ledger service)                   │
│   - seeds/01_runs.sql loaded at first boot                      │
│   - sbx-seeddemo1 seed row always present                       │
└────────────────┬────────────────────────────────────────────────┘
                 │  SDK / CLI  (CELESTO_PROVIDER=cloud or local)
                 ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Celesto Sandbox  (microVM)                       │
│                                                                   │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│   │  minimal    │  │  rootcause  │  │  testfirst  │  …         │
│   │  candidate  │  │  candidate  │  │  candidate  │            │
│   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘            │
│          │                │                │                     │
│   git clone · pip install · apply patch · pytest · preview      │
│                                                                   │
│   Safety hook: every command → logs/commands.jsonl              │
│   Network isolation: outbound HTTPS observed in live test          │
│   Snapshot: taken before risky patch step (step 5)              │
└────────────────┬─────────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────────────┐
│          Deterministic Judge  →  Leaderboard + Optional PR       │
└──────────────────────────────────────────────────────────────────┘
```

---

## How I used Celesto

| Capability | Why it was used | Evidence |
|---|---|---|
| **network_policy** | Intended network restriction capability; strict outbound blocking has not been verified. A live test reached example.com over HTTPS (HTTP 200). | `reports/live_verification.json` |
| **safety_hooks** | The project includes application-level command safety and audit logging. Independent live verification of all hooks is not established by the current evidence. | `logs/commands.jsonl` |

Without Celesto, replacing the sandbox with `subprocess.run()` would mean:
- A hallucinated `rm -rf ~/project` would destroy real files on the host.
- A prompt-injected `curl` could exfiltrate real API keys.
- All isolation disappears.

---

## Evaluation report

The repository contains a 20-run evaluation report for the demo fixture. Its original run records and metrics have not been independently verified during the live cloud test described below. Treat these as fixture/report data, not as newly reproduced live results.

| Metric | Recorded report value |
|---|---:|
| Run count | 20 (existing report; not rerun in this verification) |
| Success rate | 85% (17/20; existing report) |
| Median wall-clock | 74.55 s (existing report) |
| p90 wall-clock | 118.3 s (existing report) |
| Median boot-to-ready | 26.15 s (existing report) |
| Total cost | $0.098 USD (as recorded in `reports/reliability.json`; not independently reconciled) |

Full report: [`reports/reliability.json`](reports/reliability.json)
Failure analysis: [`reports/postmortem.md`](reports/postmortem.md)

These figures are reported repository data and should not be interpreted as results reproduced by the live verification.

---

## Live cloud verification

One disposable Celesto cloud computer (`cmp_4d520c0488eb`, Ubuntu 24.04) was created and tested on 2026-10-24.

- **Creation:** Celesto returned a computer ID and reported the computer as running.
- **Command execution:** `uname -a` and a harmless marker command executed successfully.
- **Outbound HTTPS:** A request to `https://example.com` returned HTTP 200. This demonstrates that outbound HTTPS was reachable in this test; strict outbound blocking was not demonstrated.
- **Cleanup:** Celesto subsequently reported the test computer status as `deleted`.

This was a single manual verification. It does not prove host filesystem isolation, hypervisor-level network containment, or cleanup behavior for every possible failure mode. See [`reports/live_verification.json`](reports/live_verification.json).

---

## Containment status

Strict network containment and host filesystem isolation are **not verified** by the live evidence collected so far.

The live outbound HTTPS test returned HTTP 200 from `example.com`, so the tested environment allowed that outbound request. Do not interpret the presence of application-level safety checks or a NAT network setting as proof that all outbound traffic is blocked.

The existing containment report and log are retained as repository artifacts, but their claims have not been independently reproduced by the live test. See [`reports/containment.json`](reports/containment.json) and [`reports/evidence/containment.log`](reports/evidence/containment.log).

---

## State and failure design

The project includes lifecycle cleanup logic and local tests covering success, exceptions, timeouts, and cancellation. These tests support the claim that cleanup is attempted along those code paths; they do not prove that every live cloud resource is deleted under all circumstances.

In the live verification, Celesto confirmed that disposable computer `cmp_4d520c0488eb` had status `deleted`. This is evidence for that one resource only.

Trace: [`reports/failure_trace.jsonl`](reports/failure_trace.jsonl)
Policy: [`reports/failure_policy.json`](reports/failure_policy.json)

---

## Setup

### Prerequisites

- Docker Desktop (Windows/macOS) or Docker Engine + Compose v2 (Linux).
- No Celesto credentials are needed to just start the control plane and serve report files.
- For live sandbox execution: a Celesto API key and an LLM API key.

### 1. Clone the repository

```bash
git clone https://github.com/23A91A4418/patcharena.git
cd patcharena
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your keys if you want live execution.
# For running tests against the control plane only, placeholders are fine.
```

### 3. Start the stack

```bash
docker-compose up --build -d
```

Both services become healthy within 5 minutes. Check status:

```bash
docker-compose ps
# api and ledger should both show "healthy"
```

### 4. Verify the API

```bash
# Health check
curl http://localhost:8080/health
# → {"status":"ok"}

# List ledger runs (includes seeded sbx-seeddemo1)
curl http://localhost:8080/api/runs

# Insert a run
curl -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d '{"run_id":"manual-test-1","sandbox_name":"sbx-manualtest1","problem_id":"p1","state":"created","execution_target":"celesto_sandbox"}'

# Invalid execution_target → 400
curl -sw "\nHTTP %{http_code}\n" -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d '{"run_id":"bad-1","sandbox_name":"sbx-badtest001","problem_id":"p1","state":"created","execution_target":"host"}'
```

### 5. Run automated compliance tests

```bash
# In repo root (with the stack running):
python -m pytest tests/test_reports.py -v
```

### 6. Open the live dashboard (replay mode)

```bash
# Already enabled in docker-compose.yml (REPLAY_MODE=true)
open http://localhost:8080
```

---

## Candidate Strategies

| ID | Strategy | Goal |
|---|---|---|
| `minimal` | Minimal Patch | Prefer a small, targeted fix. |
| `rootcause` | Root-Cause Fix | Address the underlying cause. |
| `testfirst` | Test-First | Add a regression test and guide the fix. |
| `defensive` | Defensive Validation | Add validation and safeguards. |

---

## Report Files

| File | Description |
|---|---|
| `reports/problem.json` | Problem statement (who/agent_work/proof_output) |
| `reports/capabilities.json` | Capability descriptions and verification status |
| `reports/lifecycle.json` | Lifecycle design and cleanup behavior (not a universal live guarantee) |
| `reports/reliability.json` | Existing 20-run evaluation report; not independently reproduced in the live test |
| `reports/postmortem.md` | Failure analysis |
| `reports/containment.json` | Existing containment artifact; claims not independently verified |
| `reports/evidence/containment.log` | Existing containment log; not independently reproduced |
| `reports/failure_policy.json` | Step-7 rollback policy |
| `reports/failure_trace.jsonl` | Trace of the failed run |
| `reports/concurrency.json` | 5-job concurrency test |
| `logs/commands.jsonl` | Command audit log (all runs) |

---

## Current Limitations

- Live execution depends on Celesto credentials, LLM API access, and account limits.
- The free Celesto trial limits to one retained sandbox; use local runtime or a paid top-up for concurrency.
- Replay mode demonstrates event streaming from saved data; it does not prove fresh sandbox execution.
- GitHub PR creation requires a valid token and repository permissions.

## Eval report

The repository contains a 20-run reliability report in
`reports/reliability.json`. The recorded results show an 85% success rate,
a median wall-clock time of 74.55 seconds, a p90 wall-clock time of
103.1 seconds, a median boot-to-ready time of 26.15 seconds, and a
reported total cost of $0.098.

These figures describe the recorded report data; the complete 20-run
evaluation has not been independently reproduced during the separate live
cloud verification. The local automated test suite passed 53 tests, with
2 tests skipped. See `reports/postmortem.md` for the recorded failure analysis.

## Containment test

The project records a containment test in `reports/containment.json` and
`reports/evidence/containment.log`. A separate manual live cloud check is
documented in `reports/live_verification.json`.

During that live check, outbound HTTPS to example.com returned HTTP 200.
Therefore, strict outbound network blocking and host filesystem isolation
remain unverified. The recorded `blocked` and `host_untouched` fields should
not be interpreted as independently verified guarantees. Further live
testing is required to establish containment behavior.
