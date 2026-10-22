"""Unit tests for judge.py — 5+ cases covering gates and scoring."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from backend.models import CandidateResult, CandidateStatus


def make_candidate(
    strategy_id: str,
    final_passed: bool = True,
    lines_changed: int = 20,
    files_changed: list | None = None,
    baseline_failed: bool = True,
    preview_url: str = "",
    browser_verified: bool = False,
    at_least_one_new_pass: bool = True,
    no_regression: bool = True,
    regression_test_passed: bool = False,
) -> CandidateResult:
    now = datetime.utcnow()
    return CandidateResult(
        strategy_id=strategy_id,
        status=CandidateStatus.PASSED if final_passed else CandidateStatus.FAILED,
        final_passed=final_passed,
        baseline_failed=baseline_failed,
        lines_changed=lines_changed,
        files_changed=files_changed or ["src/app.py"],
        preview_url=preview_url,
        browser_verified=browser_verified,
        at_least_one_new_pass=at_least_one_new_pass,
        no_regression=no_regression,
        regression_test_passed=regression_test_passed,
        started_at=now - timedelta(seconds=60),
        finished_at=now,
    )


@pytest.mark.asyncio
async def test_all_pass():
    """All candidates survive gates."""
    from backend.judge import rank_candidates
    candidates = [
        make_candidate("minimal", lines_changed=5),
        make_candidate("rootcause", lines_changed=20),
        # testfirst must have regression_test_passed=True to survive Gate 7
        make_candidate("testfirst", lines_changed=15, regression_test_passed=True),
    ]
    ranked = await rank_candidates(candidates, "Fix bug", "")
    survivors = [c for c in ranked if not c.gate_failures]
    assert len(survivors) == 3
    # Minimal should win (lowest diff = highest diff-size score)
    assert survivors[0].strategy_id == "minimal"


@pytest.mark.asyncio
async def test_one_fails_gate():
    """Candidate with tests failing is eliminated."""
    from backend.judge import rank_candidates
    candidates = [
        make_candidate("minimal", final_passed=True, lines_changed=10),
        make_candidate("rootcause", final_passed=False, lines_changed=5),
    ]
    ranked = await rank_candidates(candidates, "Fix bug", "")
    survivors = [c for c in ranked if not c.gate_failures]
    eliminated = [c for c in ranked if c.gate_failures]
    assert len(survivors) == 1
    assert survivors[0].strategy_id == "minimal"
    assert eliminated[0].strategy_id == "rootcause"


@pytest.mark.asyncio
async def test_diff_too_large():
    """Candidate with oversized diff is eliminated."""
    from backend.judge import rank_candidates
    candidates = [
        make_candidate("minimal", lines_changed=10),
        make_candidate("rootcause", lines_changed=400),  # > 300 limit
    ]
    ranked = await rank_candidates(candidates, "Fix bug", "")
    survivors = [c for c in ranked if not c.gate_failures]
    assert len(survivors) == 1
    assert survivors[0].strategy_id == "minimal"


@pytest.mark.asyncio
async def test_nobody_survives():
    """All candidates fail — should still return a complete ranking."""
    from backend.judge import rank_candidates
    candidates = [
        make_candidate("minimal", final_passed=False),
        make_candidate("rootcause", final_passed=False),
    ]
    ranked = await rank_candidates(candidates, "Fix bug", "")
    survivors = [c for c in ranked if not c.gate_failures]
    assert len(survivors) == 0
    assert len(ranked) == 2  # still all accounted for


@pytest.mark.asyncio
async def test_preview_score_bonus():
    """Candidate with preview URL gets higher score."""
    from backend.judge import rank_candidates
    candidates = [
        make_candidate("minimal", lines_changed=10, preview_url="https://preview.example.com"),
        make_candidate("rootcause", lines_changed=10),
    ]
    ranked = await rank_candidates(candidates, "Fix bug", "")
    survivors = [c for c in ranked if not c.gate_failures]
    assert survivors[0].strategy_id == "minimal"
    assert survivors[0].score > survivors[1].score


@pytest.mark.asyncio
async def test_forbidden_file_gate():
    """Candidate that touched a forbidden file is eliminated."""
    from backend.judge import rank_candidates
    candidates = [
        make_candidate("minimal", files_changed=[".github/workflows/ci.yml"]),
    ]
    ranked = await rank_candidates(candidates, "Fix bug", "")
    survivors = [c for c in ranked if not c.gate_failures]
    assert len(survivors) == 0
    assert ranked[0].gate_failures
