"""FastAPI application: REST routes + SSE event stream."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from . import events, orchestrator, replay
from .config import REPLAY_MODE
from .github_client import open_pr, push_branch_from_sandbox
from .models import PRRequest, RunRequest, RunState
from .strategies import list_strategies

app = FastAPI(title="PatchArena API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# In-memory registry of active runs
_active_runs: dict[str, RunState] = {}


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


@app.get("/api/strategies")
async def get_strategies():
    return [s.model_dump() for s in list_strategies()]


@app.post("/api/runs")
async def start_run(req: RunRequest):
    if REPLAY_MODE:
        raise HTTPException(400, "Server is in REPLAY_MODE. Use /api/replay/<id>.")

    import uuid
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


@app.get("/api/replay/{run_id}/events")
async def replay_events(run_id: str, speed: float = 5.0):
    """Stream a saved run's events directly to the SSE client."""

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


@app.get("/api/replay/{run_id}/events")
async def replay_events(run_id: str, speed: float = 5.0):
    """Stream a saved run's events at compressed timing."""
    async def generator():
        try:
            await replay.stream_replay(run_id, events.emit, speed=speed)
        except FileNotFoundError:
            yield {"data": json.dumps({"type": "error", "data": "No saved run found"})}

    return EventSourceResponse(generator())


@app.get("/api/replay/list")
async def list_replays():
    return replay.list_saved_runs()


def _build_leaderboard(run: RunState) -> str:
    from .strategies import get_strategy
    rows = ["| Strategy | Score | Status | Lines | Preview |",
            "| --- | --- | --- | --- | --- |"]
    for sid in run.ranking:
        c = run.candidates.get(sid)
        if c:
            status = "✅" if not c.gate_failures else "❌"
            preview = f"[link]({c.preview_url})" if c.preview_url else "—"
            rows.append(f"| {sid} | {c.score:.1f} | {status} | {c.lines_changed} | {preview} |")
    return "\n".join(rows)
