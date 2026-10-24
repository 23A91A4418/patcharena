"""Postgres run-ledger helpers for the compliance API."""

from __future__ import annotations

import os
import re
from typing import Any

import psycopg
from psycopg.rows import dict_row

_pool: psycopg.AsyncConnection | None = None

SANDBOX_RE = re.compile(r"^sbx-[a-z0-9]{8,}$")
VALID_STATES = {"created", "ready", "running", "succeeded", "failed", "deleted"}

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://ledger:ledger@ledger:5432/ledger",
)


async def get_conn() -> psycopg.AsyncConnection:
    """Return a new async psycopg connection (caller must close it)."""
    return await psycopg.AsyncConnection.connect(
        DATABASE_URL,
        row_factory=dict_row,
        autocommit=False,
    )


async def list_runs() -> list[dict[str, Any]]:
    """Return all rows from the runs table."""
    async with await get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT run_id, sandbox_name, problem_id, state, execution_target,"
                " created_at, updated_at FROM runs ORDER BY id DESC"
            )
            rows = await cur.fetchall()
            return list(rows)


async def insert_run(
    run_id: str,
    sandbox_name: str,
    problem_id: str,
    state: str,
    execution_target: str,
) -> dict[str, Any]:
    """Insert a run ledger row. Raises ValueError on bad input."""
    if not SANDBOX_RE.match(sandbox_name):
        raise ValueError(f"sandbox_name {sandbox_name!r} does not match sbx-[a-z0-9]{{8,}}")
    if state not in VALID_STATES:
        raise ValueError(f"state {state!r} is not one of {sorted(VALID_STATES)}")
    if execution_target != "celesto_sandbox":
        raise ValueError(f"execution_target must be 'celesto_sandbox', got {execution_target!r}")

    async with await get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE
                    SET state = EXCLUDED.state,
                        updated_at = NOW()
                RETURNING run_id, sandbox_name, problem_id, state, execution_target,
                          created_at, updated_at
                """,
                (run_id, sandbox_name, problem_id, state, execution_target),
            )
            row = await cur.fetchone()
            await conn.commit()
            return dict(row)
