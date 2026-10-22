"""Pydantic models for PatchArena."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CandidateStatus(str, Enum):
    QUEUED = "queued"
    CLONING = "cloning"
    INSTALLING = "installing"
    BASELINE = "baseline"
    PATCHING = "patching"
    TESTING = "testing"
    SERVING = "serving"
    VERIFYING = "verifying"
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class Strategy(BaseModel):
    id: str
    name: str
    description: str
    instructions: str


class ExecResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_s: float


class EditSpec(BaseModel):
    path: str
    search: str | None = None
    replace: str | None = None
    create: bool = False
    content: str | None = None


class AgentResponse(BaseModel):
    reasoning: str
    edits: list[EditSpec]


class StepRecord(BaseModel):
    step_no: int
    edits_applied: int
    apply_errors: list[str]
    test_exit_code: int
    test_summary: str


class CandidateResult(BaseModel):
    strategy_id: str
    status: CandidateStatus = CandidateStatus.QUEUED
    sandbox_name: str = ""
    files_changed: list[str] = Field(default_factory=list)
    diff_stat: str = ""
    diff_text: str = ""
    lines_changed: int = 0
    baseline_failed: bool = False
    final_passed: bool = False
    at_least_one_new_pass: bool = False   # ≥1 previously-failing test now passes
    no_regression: bool = True            # no previously-passing test now fails
    regression_test_passed: bool = False
    preview_url: str = ""
    screenshot_path: str = ""
    browser_verified: bool = False
    safety_flags: list[str] = Field(default_factory=list)
    steps: list[StepRecord] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    score: float = 0.0
    gate_failures: list[str] = Field(default_factory=list)
    judge_explanation: str = ""


class RunState(BaseModel):
    run_id: str
    repo: str
    issue: str
    issue_title: str = ""
    issue_body: str = ""
    strategy_ids: list[str] = Field(default_factory=list)
    candidates: dict[str, CandidateResult] = Field(default_factory=dict)
    ranking: list[str] = Field(default_factory=list)
    winner_id: str | None = None
    pr_url: str = ""
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None


class ArenaEvent(BaseModel):
    ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    run_id: str
    strategy_id: str = ""
    type: str  # status | log | step | result | judge | pr
    data: Any


class RunRequest(BaseModel):
    repo: str
    issue_number: int
    strategy_ids: list[str] = Field(default=["minimal", "rootcause", "testfirst"])


class PRRequest(BaseModel):
    run_id: str
