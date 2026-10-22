"""Deterministic judge: hard gates, scoring, and LLM explanation."""

from __future__ import annotations

import re

from . import llm
from .models import CandidateResult

MAX_DIFF_LINES = 300

# Score weights
W_TESTS = 40
W_DIFF_SIZE = 25
W_PREVIEW = 15
W_BROWSER = 10
W_LLM = 10


async def rank_candidates(
    candidates: list[CandidateResult],
    issue_title: str,
    issue_body: str,
) -> list[CandidateResult]:
    """Apply hard gates, score survivors, and sort descending."""
    survivors = []
    eliminated = []

    for c in candidates:
        failures = _check_gates(c)
        c.gate_failures = failures
        if not failures:
            survivors.append(c)
        else:
            eliminated.append(c)

    # Score survivors
    min_lines = min((c.lines_changed for c in survivors if c.lines_changed > 0), default=1)
    max_lines = max((c.lines_changed for c in survivors if c.lines_changed > 0), default=1)

    for c in survivors:
        c.score = _score(c, min_lines, max_lines)

    # Get LLM rubric for each survivor
    for c in survivors:
        c.score += await _llm_rubric(c, issue_title, issue_body)

    # Sort: score desc, files_changed asc, duration asc
    survivors.sort(key=lambda c: (
        -c.score,
        len(c.files_changed),
        (c.finished_at - c.started_at).total_seconds() if c.finished_at and c.started_at else 9999,
    ))

    # Add explanation only for winner
    if survivors:
        survivors[0].judge_explanation = await _judge_explanation(
            survivors, eliminated, issue_title
        )

    return survivors + eliminated


def _check_gates(c: CandidateResult) -> list[str]:
    """Return list of failure reasons. Empty = survivor."""
    failures = []

    # Gate 1: final tests must pass
    if not c.final_passed:
        failures.append("Final test did not pass (exit code != 0)")

    # Gate 2: at least one previously-failing test must now pass
    if c.final_passed and not c.at_least_one_new_pass:
        failures.append("No previously-failing test was newly fixed")

    # Gate 3: no previously-passing test may now fail (regression)
    if not c.no_regression:
        failures.append("Regression introduced: a previously-passing test now fails")

    # Gate 4: diff must be non-empty
    if c.lines_changed == 0:
        failures.append("Diff is empty (no changes made)")

    # Gate 5: diff must not exceed limit
    if c.lines_changed > MAX_DIFF_LINES:
        failures.append(f"Diff too large ({c.lines_changed} > {MAX_DIFF_LINES} lines changed)")

    # Gate 6: no forbidden files touched
    forbidden = [".github", ".env", ".pem", ".key", "package-lock", "poetry.lock"]
    for f in c.files_changed:
        if any(pat in f for pat in forbidden):
            failures.append(f"Forbidden file touched: {f}")

    # Gate 7: testfirst regression test must be confirmed
    if c.strategy_id == "testfirst" and not c.regression_test_passed:
        failures.append("Test-first strategy: regression test not confirmed")

    return failures


def _score(c: CandidateResult, min_lines: int, max_lines: int) -> float:
    score = 0.0

    # Tests (40 pts): all gates passed = full 40
    score += W_TESTS  # only survivors reach here

    # Diff size (25 pts): smaller is better
    if max_lines > min_lines:
        ratio = (max_lines - c.lines_changed) / (max_lines - min_lines)
        score += W_DIFF_SIZE * max(0.0, min(1.0, ratio))
    else:
        score += W_DIFF_SIZE  # all same size

    # Preview (15 pts)
    if c.preview_url:
        score += W_PREVIEW

    # Browser verified (10 pts)
    if c.browser_verified:
        score += W_BROWSER

    return score


async def _llm_rubric(c: CandidateResult, issue_title: str, issue_body: str) -> float:
    """Ask LLM to score 0-10 for readability, root cause, no hacks."""
    prompt = f"""Score this code patch 0-10 on: readability, addressing root cause, avoiding hacks.

Issue: {issue_title}

Diff:
{c.diff_text[:3000]}

Return ONLY JSON: {{"score": <int 0-10>, "reason": "one sentence"}}"""
    try:
        resp = await llm.json_call(prompt)
        raw_score = float(resp.get("score", 5))
        # Map 0-10 → 0-10 points
        return raw_score
    except Exception:
        return 5.0  # neutral default


async def _judge_explanation(
    survivors: list[CandidateResult],
    eliminated: list[CandidateResult],
    issue_title: str,
) -> str:
    """Generate a natural-language explanation of why the winner won."""
    winner = survivors[0]
    other_scores = [
        f"{c.strategy_id}: {c.score:.1f} pts" for c in survivors[1:]
    ]
    elim_reasons = [
        f"{c.strategy_id}: {', '.join(c.gate_failures[:2])}" for c in eliminated
    ]

    prompt = f"""You are explaining the result of an AI patch competition.

Issue: {issue_title}
Winner: {winner.strategy_id} ({winner.score:.1f} pts)
Other survivors: {other_scores or 'none'}
Eliminated: {elim_reasons or 'none'}
Winner diff size: {winner.lines_changed} lines
Winner files changed: {winner.files_changed}

Write 2-3 sentences explaining why the winner was chosen and what each other candidate did.
Be specific and direct. No fluff."""
    try:
        return await llm.text_call(prompt)
    except Exception:
        return f"{winner.strategy_id} won with {winner.score:.1f} points."
