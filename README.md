# PatchArena 🥊

> AI writes patches nobody trusts. We make them compete and prove it.

[![Celesto](https://img.shields.io/badge/Powered%20by-Celesto-6366f1)](https://celesto.ai)

---

## What It Does

PatchArena takes a GitHub issue, launches **2-3 isolated Celesto sandboxes in parallel**, each running a different AI fix strategy. Every candidate is verified by:

1. Running the real test suite (exit code, not LLM claims)
2. Booting the app and publishing a live preview URL
3. Taking a screenshot and checking it with a vision LLM

A deterministic judge scores survivors. The winner becomes a real GitHub PR with test evidence, a screenshot, and a live preview link.

---

## How Celesto Powers PatchArena

| Feature | How PatchArena Uses It |
|---|---|
| **Parallel computers** | 2-3 sandboxes run concurrently per arena run |
| **Isolation** | Each strategy runs in its own microVM — untrusted code stays off our server |
| **Persistence** | Sandboxes stay alive after the run for live preview and pause/resume |
| **CelestoFS / disk** | 10GB disk for clone + install + artifacts |
| **Published ports** | App preview URL served from inside the sandbox |
| **Browser access** | Screenshot and health verification |

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/<you>/patcharena
cd patcharena
pip install -e .

# 2. Configure
cp .env.example .env
# Fill in: CELESTO_API_KEY, LLM_API_KEY, GITHUB_TOKEN

# 3. Run Phase 0 spike (verify Celesto works)
python scripts/spike.py

# 4. Start the server
uvicorn backend.main:app --reload --port 8000

# 5. Open http://localhost:8000
```

---

## Architecture

```
Browser (EventSource SSE)
        │
  FastAPI (main.py)
        │
  orchestrator.py ──── asyncio.gather ──── candidate × N
        │                                      │
  judge.py                             celesto_client.py
                                             │
                                    Celesto Sandbox (microVM)
                          git clone → install → test → patch → test → serve
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `CELESTO_API_KEY` | Your Celesto API key |
| `LLM_PROVIDER` | `gemini` / `anthropic` / `openai` |
| `LLM_API_KEY` | LLM API key |
| `LLM_MODEL` | Model name (e.g. `gemini-2.0-flash`) |
| `GITHUB_TOKEN` | Fine-grained token: contents + pull_requests on your fork |
| `MAX_PARALLEL` | Max concurrent sandboxes (default: 3) |
| `SANDBOX_TIMEOUT_S` | Per-run timeout in seconds (default: 420) |

---

## Strategies

| ID | Name | Description |
|---|---|---|
| `minimal` | Minimal Patch | Smallest possible fix |
| `rootcause` | Root-Cause Fix | Fix where the bug originates |
| `testfirst` | Test-First | Regression test first, then fix |
| `defensive` | Defensive Validation | Fix + add guards against recurrence |

---

## Running Tests

```bash
pytest tests/ -q                   # unit tests
pytest tests/ -m slow -v           # integration (needs CELESTO_API_KEY)
```

## Known Limitations

- Install/test commands are hardcoded for the demo repo
- Playwright must be installed locally for screenshots if Celesto has no native screenshot API
- `REPLAY_MODE=true` streams a saved run without needing live API keys