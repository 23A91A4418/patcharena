# PatchArena

> AI-generated patches shouldn't be trusted blindly. Let them compete, test them, and choose a winner based on evidence.



**Repository:** [https://github.com/23A91A4418/patcharena](https://github.com/23A91A4418/patcharena)

## Overview

PatchArena is an experimental AI-assisted bug-fixing arena. It evaluates multiple patch strategies against the same issue, collects verification evidence, and uses a deterministic judge to rank candidate results.

The project includes a replay mode that streams a saved run to the dashboard without requiring a new live sandbox execution.

## Key Features

- **Competing strategies:** Minimal Patch, Root-Cause Fix, Test-First, and Defensive Validation.
- **Sandbox orchestration:** Integrates with Celesto for isolated candidate execution.
- **Test-based verification:** Uses test results as evidence when evaluating candidate patches.
- **Preview and screenshot verification:** Includes app health checks, Playwright screenshot capture, and screenshot-based visual verification.
- **Deterministic judging:** Ranks candidates using the project's scoring and verification results.
- **Live event streaming:** Streams run events to the browser using Server-Sent Events (SSE).
- **Replay mode:** Replays saved run events for a repeatable demonstration.
- **GitHub integration:** Includes support for preparing a pull request for a winning candidate.

## How It Works

1. Provide a repository and issue through the dashboard.
2. Select the candidate strategies to evaluate.
3. Run the arena so candidates can attempt fixes in isolated environments.
4. Collect test results and available preview or screenshot verification evidence.
5. Rank the candidates and identify a winner.
6. Review the winning result and, when configured and supported by the run, use the GitHub pull-request workflow.

### Architecture

```text
Browser Dashboard
       |
       | HTTP + SSE
       v
FastAPI Backend
       |
       v
Arena Orchestrator
       |
       +---- Candidate Strategy 1
       +---- Candidate Strategy 2
       +---- Candidate Strategy 3
       |
       v
Celesto Client
       |
       v
Isolated Execution Environments
       |
       +---- Clone and prepare repository
       +---- Apply candidate patch
       +---- Run tests
       +---- Start app and verify preview
       +---- Capture screenshot when available
       |
       v
Deterministic Judge
       |
       v
Ranked Results and Optional GitHub PR
```

## Candidate Strategies

| ID          | Strategy             | Goal                                               |
| ----------- | -------------------- | -------------------------------------------------- |
| `minimal`   | Minimal Patch        | Prefer a small, targeted fix.                      |
| `rootcause` | Root-Cause Fix       | Address the underlying cause of the bug.           |
| `testfirst` | Test-First           | Add a regression test and use it to guide the fix. |
| `defensive` | Defensive Validation | Add appropriate validation and safeguards.         |

## Requirements

- Python 3.11 or newer.
- Git.
- Celesto credentials for live sandbox execution.
- An API key for the configured LLM provider.
- A GitHub token for GitHub operations.
- Playwright and its browser dependencies if using the local screenshot fallback.

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/23A91A4418/patcharena.git
cd patcharena
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell, activate it with:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -e .
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and configure the variables required by your chosen workflow.

| Variable            | Purpose                                                                     |
| ------------------- | --------------------------------------------------------------------------- |
| `CELESTO_API_KEY`   | Authentication for live Celesto execution.                                  |
| `LLM_PROVIDER`      | Configured LLM provider, such as `gemini`, `anthropic`, or `openai`.        |
| `LLM_API_KEY`       | API key for the selected LLM provider.                                      |
| `LLM_MODEL`         | Model name used by the application.                                         |
| `GITHUB_TOKEN`      | Authentication for supported GitHub operations.                             |
| `MAX_PARALLEL`      | Maximum candidate concurrency, subject to configuration and account limits. |
| `SANDBOX_TIMEOUT_S` | Candidate execution timeout in seconds.                                     |
| `DEMO_REPO` | Demo repository URL used by the application. |
| `MAX_AGENT_STEPS` | Maximum agent steps, defaulting to 4. |

Use the variable names and defaults defined in `backend/config.py` and `.env.example` as the source of truth.

**Security:** Never commit `.env` or API tokens to Git.

### 5. Start the application

```bash
uvicorn backend.main:app --reload --port 8000
```

Open the dashboard at [http://localhost:8000](http://localhost:8000).

The API documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

## Replay Mode

PatchArena includes saved-run replay for demonstrations and development.

Configure:

```env
REPLAY_MODE=true
```

Restart the server after changing the environment variable.

In replay mode, use the dashboard's replay controls to select a saved run. Replay mode is intended to demonstrate event streaming and the results represented by saved run data; it does not prove that a new Celesto execution has occurred.

## Running Tests

Run the non-slow test suite:

```bash
python -m pytest tests/ -v -m "not slow"
```

Run the slow tests separately when the required credentials and execution environment are available:

```bash
python -m pytest tests/ -v -m slow
```

## Current Limitations

- Live execution depends on external API access, credentials, sandbox availability, and account limits.
- Replay results come from saved event data and are distinct from fresh live execution results.
- Screenshot verification depends on the app preview being available and the required screenshot and vision-model dependencies being configured.
- Supported repository layouts, install commands, and test commands may require adaptation for different projects.
- GitHub pull-request creation requires appropriate repository permissions and a valid winning candidate artifact.
