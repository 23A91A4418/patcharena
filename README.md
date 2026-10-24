# PatchArena

> AI-generated patches shouldn't be trusted blindly. Let them compete, test them, and choose a winner based on evidence.

**Repository:** https://github.com/23A91A4418/patcharena

## Problem statement

Software engineering teams and open-source maintainers receive bug reports and need AI-generated fixes evaluated objectively before merging. A patch that appears correct may fail tests, introduce regressions, or make unnecessary changes. Running untrusted code also introduces security risks.

PatchArena is designed to compare multiple AI-generated patch strategies in a sandbox-oriented workflow. It orchestrates candidate execution, collects testing and code-change evidence, and ranks results using a deterministic judging process.

The goal is to help developers choose a promising fix based on measurable evidence rather than trusting an AI-generated explanation alone.

## Architecture

```text
                 Operator / Browser
                        |
                  HTTP / SSE
                        |
                        v
                FastAPI Backend
                   Port 8080
                        |
             +----------+----------+
             |                     |
             v                     v
       Run Ledger API        Arena Orchestrator
             |                     |
             v                     v
          Postgres          Celesto SDK / CLI
             |                     |
       Run metadata                 v
                             Sandbox execution
                             /       |       \
                        Minimal  Root-cause  Test-first
                        patch      patch       patch
                             \       |       /
                              v      v      v
                         Test and patch evidence
                                  |
                                  v
                           Deterministic Judge
                                  |
                                  v
                           Ranked Leaderboard
```

### Main components

- **Frontend:** Displays candidate strategies, scores, and evaluation results.
- **FastAPI backend:** Coordinates the application and exposes API endpoints.
- **Run ledger:** Uses PostgreSQL to store and retrieve run records.
- **Celesto integration:** Provides the intended sandbox execution layer for agent commands.
- **Safety and audit logic:** Applies application-level command checks and records command activity.
- **Deterministic judge:** Compares candidate results using testing and patch-quality evidence.
- **Replay mode:** Demonstrates the dashboard and event flow using saved data; it is not proof of fresh sandbox execution.

## How I used Celesto

PatchArena integrates Celesto as its intended execution layer for running agent commands in a separate sandbox environment.

The workflow is designed to:

1. Create a sandbox for a candidate.
2. Clone or prepare the target repository inside the sandbox.
3. Apply a candidate patch.
4. Run the relevant test suite.
5. Collect patch and test evidence.
6. Evaluate the candidate.
7. Attempt sandbox cleanup after execution.

### Capabilities and evidence

| Capability | Intended use | Evidence and limitations |
|---|---|---|
| `network_policy` | Network restriction for sandboxed execution | `reports/live_verification.json` records that outbound HTTPS was reachable. Strict outbound blocking is not verified. |
| `safety_hooks` | Application-level command safety and audit logging | `logs/commands.jsonl`; this does not independently verify every hook or establish host isolation. |

The application includes command audit logging and safety checks. These are useful safeguards, but they should not be confused with independently verified operating-system or hypervisor-level security boundaries.

### Why sandboxing matters

Running untrusted generated commands directly on a developer's host can expose local files, credentials, and repositories to accidental or malicious changes. A sandbox-oriented execution design helps separate agent work from the developer's normal environment.

The strength of that separation depends on the actual sandbox configuration and its enforcement. The live verification documented below does not establish complete host filesystem isolation or strict network containment.

## Candidate strategies

| ID | Strategy | Goal |
|---|---|---|
| `minimal` | Minimal Patch | Prefer a small, targeted change. |
| `rootcause` | Root-Cause Fix | Address the underlying cause of the issue. |
| `testfirst` | Test-First | Add a regression test to guide the fix. |
| `defensive` | Defensive Validation | Add validation and safeguards. |

The leaderboard is intended to help compare candidate outcomes using test results, patch characteristics, and available verification evidence. A higher score is a ranking signal, not a guarantee that a patch is correct or safe to merge.

## Eval report

The repository contains a 20-run reliability report at `reports/reliability.json`. These are recorded report results and have not been independently reproduced through the separate live cloud verification.

| Metric | Recorded value |
|---|---:|
| Run count | 20 |
| Success rate | 85% (17 of 20) |
| Median wall-clock time | 74.55 seconds |
| P90 wall-clock time | 103.1 seconds |
| Median boot-to-ready time | 26.15 seconds |
| Total recorded cost | $0.098 USD |

The summary values above are calculated from the recorded run rows. They should not be interpreted as a newly reproduced 20-run live evaluation.

### Local test results

The local automated test suite completed with:

- **53 passed**
- **2 skipped**

These results verify the exercised local test cases. They do not establish that every live cloud execution, cleanup operation, or containment scenario succeeds.

### Failure analysis

See [`reports/postmortem.md`](reports/postmortem.md) for the recorded evaluation failure analysis.

Additional report files:

- [`reports/reliability.json`](reports/reliability.json)
- [`reports/failure_policy.json`](reports/failure_policy.json)
- [`reports/failure_trace.jsonl`](reports/failure_trace.jsonl)

## Live cloud verification

One disposable Celesto cloud computer was manually tested on October 24, 2026.

| Check | Result |
|---|---|
| Cloud computer creation | Passed |
| Command execution | Passed |
| Outbound HTTPS request to `example.com` | HTTP 200; outbound access was reachable |
| Cleanup | Celesto reported the disposable computer as deleted |
| Strict network containment | Not verified |
| Host filesystem isolation | Not verified |

Detailed evidence is available in [`reports/live_verification.json`](reports/live_verification.json).

This was a single manual verification. It does not independently reproduce the 20-run evaluation or establish cleanup behavior for every possible failure mode.

## Containment test

The repository contains a recorded containment test in [`reports/containment.json`](reports/containment.json) and [`reports/evidence/containment.log`](reports/evidence/containment.log).

**Containment status: not independently verified.**

The separate live cloud test successfully reached `https://example.com` over HTTPS and received HTTP 200. Therefore, strict outbound network blocking was not demonstrated. Host filesystem isolation and hypervisor-level containment also remain unverified.

The existing containment artifacts are retained for inspection, but their recorded `blocked` and `host_untouched` values should not be interpreted as independently confirmed guarantees. Additional testing is needed before making stronger security claims.

## State and failure design

PatchArena includes lifecycle cleanup logic and local tests covering success, exceptions, timeouts, and cancellation.

The recovery policy recorded in `reports/failure_policy.json` is `fresh` for the documented failure at step 7 of 10. The intended behavior is to stop using the failed candidate, attempt cleanup, and record the outcome.

Local tests support the claim that cleanup is attempted along the tested code paths. The single live deletion check confirms the reported deletion of one disposable computer only; it does not prove successful cleanup under every live failure condition.

See:

- [`reports/lifecycle.json`](reports/lifecycle.json)
- [`reports/failure_policy.json`](reports/failure_policy.json)
- [`reports/failure_trace.jsonl`](reports/failure_trace.jsonl)

## Setup

### Prerequisites

- Docker Desktop or Docker Engine with Docker Compose v2.
- Python and the project dependencies for local development and tests.
- Celesto credentials and an LLM API key for live agent execution.

The control plane and saved report/demo functionality can be explored without performing live sandbox execution, subject to the configured environment.

### 1. Clone the repository

```bash
git clone https://github.com/23A91A4418/patcharena.git
cd patcharena
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and provide valid credentials for live execution. Keep real credentials private and never commit `.env`.

For control-plane and replay-mode exploration, use the configuration documented in `.env.example` and `docker-compose.yml`.

### 3. Start the application

```bash
docker-compose up --build -d
```

Check service status:

```bash
docker-compose ps
```

The `api` and `ledger` services should become healthy according to their configured health checks.

### 4. Verify the API

Check application health:

```bash
curl http://localhost:8080/health
```

Expected response:

```json
{"status":"ok"}
```

List ledger records:

```bash
curl http://localhost:8080/api/runs
```

A fresh database is expected to include the seeded `sbx-seeddemo1` record.

Create a valid run record:

```bash
curl -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d '{"run_id":"manual-test-1","sandbox_name":"sbx-manualtest1","problem_id":"p1","state":"created","execution_target":"celesto_sandbox"}'
```

Test validation with an invalid execution target:

```bash
curl -sw "\nHTTP %{http_code}\n" \
  -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d '{"run_id":"bad-1","sandbox_name":"sbx-badtest001","problem_id":"p1","state":"created","execution_target":"host"}'
```

The invalid request is expected to return HTTP 400.

### 5. Run automated tests

Activate the project's virtual environment if you have one, then run:

```bash
python -m pytest -q
```

To run the report compliance tests specifically:

```bash
python -m pytest tests/test_reports.py -v
```

### 6. Open the dashboard

Visit:

http://localhost:8080

The configured replay mode demonstrates the dashboard and saved event flow. It does not prove that new sandbox executions have occurred.

## Report files

| File | Purpose |
|---|---|
| `reports/problem.json` | Problem definition and expected proof output |
| `reports/capabilities.json` | Celesto capability descriptions and evidence |
| `reports/lifecycle.json` | Lifecycle and cleanup report |
| `reports/reliability.json` | Recorded 20-run evaluation data |
| `reports/postmortem.md` | Failure analysis |
| `reports/containment.json` | Containment test record and verification status |
| `reports/evidence/containment.log` | Recorded containment evidence |
| `reports/live_verification.json` | Manual live cloud verification |
| `reports/failure_policy.json` | Recovery policy for the documented failure |
| `reports/failure_trace.jsonl` | Failure and recovery trace |
| `reports/concurrency.json` | Recorded concurrency test report |
| `logs/commands.jsonl` | Command audit log |

## Demo video

**Status: pending recording.**

The walkthrough video will demonstrate the dashboard, candidate leaderboard, Celesto integration, evaluation reports, and current verification limitations.

Target duration: under 3 minutes.

Once recorded, save the video as `demo/walkthrough.mp4` or add a direct video link here.

## Current limitations

- Live sandbox execution depends on Celesto credentials, LLM API access, and account limits.
- The live verification was a single disposable-computer test, not a reproduced 20-run evaluation.
- Strict outbound network blocking and host filesystem isolation have not been independently verified.
- Local cleanup tests do not prove deletion of every live cloud resource under all failure conditions.
- Replay mode uses saved data and should not be treated as evidence of fresh execution.
- The recorded concurrency report describes account-limit failures and local parallel execution; it is not proof of five simultaneous live Celesto cloud sandboxes.
- GitHub pull-request creation requires a valid token and appropriate repository permissions.

## Responsible use of AI tools

AI-assisted development tools may be used during implementation and debugging. Any tools used to develop this submission should be disclosed accurately in accordance with the hackathon rules.

---

**PatchArena's goal:** make AI-generated patch evaluation more systematic, evidence-driven, and inspectable before a developer chooses a fix to merge.
