
"""FastAPI application: REST routes + SSE event stream."""

from __future__ import annotations

import asyncio
import json
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from . import events, ledger, orchestrator, replay
from .config import REPLAY_MODE
from .github_client import open_pr
from .models import LedgerRunRequest, PRRequest, RunRequest, RunState
from .strategies import list_strategies

app = FastAPI(title="PatchArena API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend assets directly from the frontend directory.
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/app.js")
async def frontend_javascript():
    return FileResponse("frontend/app.js", media_type="application/javascript")


@app.get("/app.css")
async def frontend_stylesheet():
    return FileResponse("frontend/app.css", media_type="text/css")


# In-memory registry of active runs.
_active_runs: dict[str, RunState] = {}


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


@app.get("/health")
async def health():
    """Liveness probe required by the challenge spec."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Ledger endpoints (compliance: GET /api/runs, POST /api/runs)
# ---------------------------------------------------------------------------

@app.get("/api/runs")
async def list_runs_ledger():
    """Return all rows from the run ledger (Postgres)."""
    try:
        rows = await ledger.list_runs()
        # Convert datetime objects to ISO strings for JSON serialisation.
        result = []
        for row in rows:
            r = dict(row)
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
            result.append(r)
        return result
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ledger unavailable: {exc}") from exc


@app.post("/api/runs", status_code=201)
async def create_run_ledger(req: LedgerRunRequest):
    """Insert a sandbox run row into the ledger. Returns 201 or 400."""
    try:
        row = await ledger.insert_run(
            run_id=req.run_id,
            sandbox_name=req.sandbox_name,
            problem_id=req.problem_id,
            state=req.state,
            execution_target=req.execution_target,
        )
        r = dict(row)
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
        return JSONResponse(status_code=201, content=r)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ledger unavailable: {exc}") from exc


# ---------------------------------------------------------------------------
# Arena run endpoints (renamed from /api/runs to /api/arena/runs)
# ---------------------------------------------------------------------------


@app.get("/api/strategies")
async def get_strategies():
    return [s.model_dump() for s in list_strategies()]


@app.post("/api/arena/runs")
async def start_arena_run(req: RunRequest):
    if REPLAY_MODE:
        raise HTTPException(
            status_code=400,
            detail="Server is in REPLAY_MODE. Use /api/replay/{id}.",
        )

    run_id = str(uuid.uuid4())[:8]

    async def _run_and_store():
        run = await orchestrator.run_arena(
            req.repo, req.issue_number, req.strategy_ids, run_id=run_id
        )
        _active_runs[run_id] = run

    asyncio.create_task(_run_and_store())
    return {"run_id": run_id, "status": "started"}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = _active_runs.get(run_id) or orchestrator.get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    return run.model_dump()


@app.get("/api/replay/list")
async def list_replays():
    return replay.list_saved_runs()


@app.get("/api/replay/{run_id}/state")
async def replay_state(run_id: str):
    """Return the saved state for a replay run."""
    folder = "golden" if run_id == "golden" else run_id
    path = os.path.join("runs", folder, "state.json")

    if not os.path.isfile(path):
        raise HTTPException(
            status_code=404,
            detail=f"Saved replay state not found: {run_id}",
        )

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not read saved replay state",
        ) from exc


@app.get("/api/replay/{run_id}/events")
async def replay_events(run_id: str, speed: float = 5.0):
    """Stream a saved run's events directly to the SSE client."""

    if speed <= 0:
        raise HTTPException(status_code=400, detail="Speed must be greater than 0")

    async def generator():
        queue = asyncio.Queue()

        async def capture(event_run_id, strategy_id, event_type, data):
            await queue.put({
                "data": json.dumps({
                    "run_id": event_run_id,
                    "strategy_id": strategy_id,
                    "type": event_type,
                    "data": data,
                })
            })

        async def produce():
            try:
                await replay.stream_replay(run_id, capture, speed=speed)
            except FileNotFoundError:
                await queue.put({
                    "data": json.dumps({
                        "run_id": run_id,
                        "strategy_id": "",
                        "type": "error",
                        "data": f"No saved run found: {run_id}",
                    })
                })
            finally:
                await queue.put(None)

        producer = asyncio.create_task(produce())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            if not producer.done():
                producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    return EventSourceResponse(generator())


@app.post("/api/runs/{run_id}/pr")
async def open_pr_endpoint(run_id: str):
    run = _active_runs.get(run_id) or orchestrator.get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    if not run.winner_id:
        raise HTTPException(400, "No winner yet")

    winner = run.candidates.get(run.winner_id)
    if not winner:
        raise HTTPException(400, "Winner candidate not found")

    branch = f"patcharena/{run_id}/{run.winner_id}"
    leaderboard = _build_leaderboard(run)

    pr_url = await open_pr(
        repo_url=run.repo,
        branch=branch,
        issue_number=int(run.issue),
        winner_strategy_id=run.winner_id,
        leaderboard_md=leaderboard,
        preview_url=winner.preview_url,
        screenshot_path=winner.screenshot_path,
        judge_explanation=winner.judge_explanation,
    )
    run.pr_url = pr_url
    return {"pr_url": pr_url}


def _build_leaderboard(run: RunState) -> str:
    rows = [
        "| Strategy | Score | Status | Lines | Preview |",
        "| --- | --- | --- | --- | --- |",
    ]

    for sid in run.ranking:
        candidate = run.candidates.get(sid)
        if candidate:
            status = "✅" if not candidate.gate_failures else "❌"
            preview = f"[link]({candidate.preview_url})" if candidate.preview_url else "—"
            rows.append(
                f"| {sid} | {candidate.score:.1f} | {status} | "
                f"{candidate.lines_changed} | {preview} |"
            )

    return "\n".join(rows)
