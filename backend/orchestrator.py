"""Parallel orchestrator: run all candidates concurrently and judge results."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime

from . import events, judge
from .candidate import run_candidate
from .config import MAX_PARALLEL
from .github_client import fetch_issue
from .models import CandidateResult, CandidateStatus, RunState, RunStatus, Strategy
from .strategies import get_strategy

RUNS_DIR = "runs"
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_PARALLEL)
    return _semaphore


async def run_arena(
    repo: str,
    issue_number: int,
    strategy_ids: list[str],
    run_id: str | None = None,
) -> RunState:
    """Top-level orchestrator: launch parallel candidates and judge."""
    run_id = run_id or str(uuid.uuid4())[:8]
    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)

    # Fetch issue details
    issue_title, issue_body = await fetch_issue(repo, issue_number)

    strategies: list[Strategy] = [get_strategy(sid) for sid in strategy_ids]

    run = RunState(
        run_id=run_id,
        repo=repo,
        issue=str(issue_number),
        issue_title=issue_title,
        issue_body=issue_body,
        strategy_ids=strategy_ids,
        status=RunStatus.RUNNING,
        candidates={
            s.id: CandidateResult(strategy_id=s.id)
            for s in strategies
        },
    )

    _save_state(run, run_dir)

    await events.emit(run_id, "", "status", "running")
    await events.emit(run_id, "", "log",
                      f"Arena started: {len(strategies)} candidates for #{issue_number}")

    sem = _get_semaphore()

    async def bounded_run(strategy: Strategy):
        async with sem:
            return await run_candidate(strategy, run)

    tasks = [asyncio.create_task(bounded_run(s)) for s in strategies]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle exceptions — never crash the whole run
    results: list[CandidateResult] = []
    for strategy, res in zip(strategies, results_raw):
        if isinstance(res, Exception):
            run.candidates[strategy.id].status = CandidateStatus.ERROR
            await events.emit(run_id, strategy.id, "log", f"Crashed: {res}")
            results.append(run.candidates[strategy.id])
        else:
            results.append(res)

    # Judge
    await events.emit(run_id, "", "log", "Judging candidates...")
    ranking = await judge.rank_candidates(
        results,
        issue_title=issue_title,
        issue_body=issue_body,
    )

    run.ranking = [c.strategy_id for c in ranking]
    survivors = [c for c in ranking if not c.gate_failures]
    run.winner_id = survivors[0].strategy_id if survivors else None
    run.status = RunStatus.COMPLETE
    run.finished_at = datetime.utcnow()

    # Update candidates with scores
    for c in ranking:
        run.candidates[c.strategy_id] = c

    _save_state(run, run_dir)

    # Save event log for replay
    events.save_events_jsonl(run_id, os.path.join(run_dir, "events.jsonl"))

    await events.emit(run_id, "", "judge", {
        "ranking": run.ranking,
        "winner_id": run.winner_id,
        "explanation": survivors[0].judge_explanation if survivors else "No survivors",
    })

    return run


def get_run(run_id: str) -> RunState | None:
    path = os.path.join(RUNS_DIR, run_id, "state.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return RunState(**json.load(f))


def _save_state(run: RunState, run_dir: str) -> None:
    path = os.path.join(run_dir, "state.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(run.model_dump_json(indent=2))
