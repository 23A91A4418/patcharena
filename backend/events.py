"""Async event bus for SSE streaming."""

import asyncio
import json
from collections import defaultdict
from datetime import datetime

from .config import redact

# run_id -> list of subscribers (asyncio.Queue)
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
# run_id -> event history (replayed on new connect)
_history: dict[str, list[dict]] = defaultdict(list)


def _make_event(run_id: str, strategy_id: str, type_: str, data) -> dict:
    return {
        "ts": datetime.utcnow().isoformat(),
        "run_id": run_id,
        "strategy_id": strategy_id,
        "type": type_,
        "data": data,
    }


async def emit(run_id: str, strategy_id: str, type_: str, data) -> None:
    """Emit an event to all subscribers of this run."""
    event = _make_event(run_id, strategy_id, type_, data)
    # Redact sensitive data in string fields
    if isinstance(event.get("data"), str):
        event["data"] = redact(event["data"])
    _history[run_id].append(event)
    for q in _subscribers[run_id]:
        await q.put(event)


async def subscribe(run_id: str) -> asyncio.Queue:
    """Subscribe to a run's event stream. Replays history first."""
    q: asyncio.Queue = asyncio.Queue()
    # Replay history
    for event in _history[run_id]:
        await q.put(event)
    _subscribers[run_id].append(q)
    return q


def unsubscribe(run_id: str, q: asyncio.Queue) -> None:
    try:
        _subscribers[run_id].remove(q)
    except ValueError:
        pass


def get_history(run_id: str) -> list[dict]:
    return list(_history[run_id])


def save_events_jsonl(run_id: str, path: str) -> None:
    """Save event history to a JSONL file for replay."""
    with open(path, "w", encoding="utf-8") as f:
        for event in _history[run_id]:
            f.write(json.dumps(event) + "\n")
