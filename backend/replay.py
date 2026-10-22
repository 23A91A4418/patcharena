"""Replay a saved run's event stream at compressed original timing."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime

GOLDEN_RUN_DIR = os.path.join("runs", "golden")


async def stream_replay(run_id: str, emit_fn, speed: float = 5.0) -> None:
    """
    Replay events from runs/<run_id>/events.jsonl at compressed timing.
    Use run_id='golden' to stream the bundled golden demo run.
    speed=5 means 5x faster than real time.
    """
    if run_id == "golden":
        path = os.path.join(GOLDEN_RUN_DIR, "events.jsonl")
    else:
        path = os.path.join("runs", run_id, "events.jsonl")

    if not os.path.exists(path):
        raise FileNotFoundError(f"No event log for run: {run_id}")

    raw_events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw_events.append(json.loads(line))

    if not raw_events:
        return

    # Compute delays relative to the FIRST event (not cumulative per loop)
    first_ts = datetime.fromisoformat(raw_events[0]["ts"])

    prev_delay = 0.0
    for event in raw_events:
        event_ts = datetime.fromisoformat(event["ts"])
        original_delay = (event_ts - first_ts).total_seconds()
        compressed_delay = original_delay / speed
        # Sleep only the incremental difference
        sleep_time = max(0.0, compressed_delay - prev_delay)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        prev_delay = compressed_delay

        await emit_fn(
            event["run_id"],
            event.get("strategy_id", ""),
            event["type"],
            event["data"],
        )


def list_saved_runs() -> list[dict]:
    """Return a list of saved run IDs and their state.json summaries."""
    runs = []
    if not os.path.exists("runs"):
        return runs
    for run_id in os.listdir("runs"):
        state_path = os.path.join("runs", run_id, "state.json")
        if os.path.exists(state_path):
            try:
                with open(state_path, encoding="utf-8") as f:
                    state = json.load(f)
                runs.append({
                    "run_id": run_id,
                    "repo": state.get("repo", ""),
                    "status": state.get("status", ""),
                    "winner_id": state.get("winner_id"),
                    "created_at": state.get("created_at", ""),
                })
            except Exception:
                pass
    return sorted(runs, key=lambda r: r.get("created_at", ""), reverse=True)
