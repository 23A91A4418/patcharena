"""Per-strategy candidate pipeline: clone → install → baseline → patch → test → serve → verify.

STEP NUMBERING (for recovery policy documentation):
  1. Sandbox creation + boot
  2. Repository clone
  3. Dependency install
  4. Baseline test (verify issue exists)
  5. Agent loop – patch application
  6. Final authoritative test run
  7. Diff collection + safety scan          ← designed failure point
  8. Regression test check (testfirst only)
  9. Serve + preview/screenshot verify
 10. Cleanup (always)

Recovery policy: if step 7 fails, the pipeline logs the failure, marks the
candidate as FAILED, and proceeds to cleanup (step 10). Because all
application-owned commands are trusted and agent-generated commands are
validated by the safety hook before reaching Celesto, there is no state to
roll back to at a snapshot level in this implementation. The failure is
recorded in the trace and the sandbox is always deleted in the finally block.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

from . import events
from .agent import run_agent_loop
from .celesto_client import CommandBlockedError, Sandbox, make_sandbox_name
from .config import SANDBOX_TIMEOUT_S
from .models import CandidateResult, CandidateStatus, RunState, Strategy
from .test_parser import compare_test_results
from .verify import run_serve_verify, safety_scan

WORK_DIR = "~/work/app"
ARTIFACTS_DIR = "~/work/artifacts"

TOTAL_STEPS = 10
FAILURE_INJECTION_STEP = int(os.environ.get("INJECT_FAILURE_AT_STEP", "0"))
"""Set INJECT_FAILURE_AT_STEP=7 in tests to simulate the designed crash.
This env-var is checked only in _step_gate(). It must never be set in
production; the default 0 means no injection."""


def _step_gate(step: int, label: str) -> None:
    """Raise a deterministic error at the configured injection step (tests only)."""
    if FAILURE_INJECTION_STEP and step == FAILURE_INJECTION_STEP:
        raise RuntimeError(
            f"[FAILURE_INJECTION] Simulated failure at step {step} ({label})"
        )


def _trace(run_id: str, strategy_id: str, step: int, event: str, **extra) -> None:
    """Append one line to the failure trace JSONL (for recovery policy audit)."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "candidate_id": strategy_id,
        "step": step,
        "total_steps": TOTAL_STEPS,
        "event": event,
        **extra,
    }
    try:
        os.makedirs("reports", exist_ok=True)
        with open("reports/failure_trace.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


async def run_candidate(strategy: Strategy, run: RunState) -> CandidateResult:
    """Full pipeline for one candidate strategy."""
    result = run.candidates[strategy.id]
    result.started_at = datetime.utcnow()
    result.sandbox_name = make_sandbox_name(run.run_id, strategy.id)

    try:
        await asyncio.wait_for(
            _pipeline(strategy, run, result),
            timeout=SANDBOX_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        result.status = CandidateStatus.TIMEOUT
        await events.emit(run.run_id, strategy.id, "status", CandidateStatus.TIMEOUT)
    except CommandBlockedError as e:
        result.status = CandidateStatus.ERROR
        await events.emit(run.run_id, strategy.id, "log",
                          f"Command blocked by safety hook: {str(e)[:200]}")
        await events.emit(run.run_id, strategy.id, "status", CandidateStatus.ERROR)
    except Exception as e:
        result.status = CandidateStatus.ERROR
        await events.emit(run.run_id, strategy.id, "log", f"Pipeline error: {e}")
        await events.emit(run.run_id, strategy.id, "status", CandidateStatus.ERROR)
    finally:
        result.finished_at = datetime.utcnow()
        await events.emit(run.run_id, strategy.id, "result", result.model_dump(mode="json"))

    return result


async def _pipeline(strategy: Strategy, run: RunState, result: CandidateResult) -> None:
    emit = events.emit
    rid = run.run_id
    sid = strategy.id

    repo = run.repo
    install_cmd = _get_install_cmd(repo)
    test_cmd = _get_test_cmd(repo)
    start_cmd = _get_start_cmd(repo)
    app_port = _get_app_port(repo)

    async def set_status(s: CandidateStatus):
        result.status = s
        await emit(rid, sid, "status", s.value)

    sandbox = None
    try:
        # ── Step 1: Create sandbox ────────────────────────────────────────
        _step_gate(1, "sandbox-create")
        await set_status(CandidateStatus.CLONING)
        _trace(rid, sid, 1, "step_started")
        sandbox = await Sandbox.create(
            name=result.sandbox_name,
            run_id=rid,
            strategy_id=sid,
            emit=emit,
        )
        # Update sandbox_name to the actual cloud computer ID
        result.sandbox_name = sandbox.name
        _trace(rid, sid, 1, "sandbox_created", sandbox_name=sandbox.name)

        # ── Step 2: Clone repo ────────────────────────────────────────────
        _step_gate(2, "git-clone")
        _trace(rid, sid, 2, "step_started")
        branch = f"patcharena/{run.run_id}/{sid}"
        clone_result = await sandbox.run(
            f"git clone {repo} {WORK_DIR} && "
            f"cd {WORK_DIR} && git checkout -b {branch}",
            timeout=120,
            trusted=True,
        )
        if clone_result.exit_code != 0:
            raise RuntimeError(f"Clone failed: {clone_result.stderr[:200]}")
        _trace(rid, sid, 2, "step_completed")

        # ── Step 3: Install dependencies ──────────────────────────────────
        _step_gate(3, "pip-install")
        await set_status(CandidateStatus.INSTALLING)
        _trace(rid, sid, 3, "step_started")
        install_result = await sandbox.run(
            f"cd {WORK_DIR} && {install_cmd}",
            timeout=180,
            trusted=True,
        )
        if install_result.exit_code != 0:
            raise RuntimeError(f"Install failed: {install_result.stderr[:200]}")
        await sandbox.run(f"mkdir -p {ARTIFACTS_DIR}", timeout=10, trusted=True)
        _trace(rid, sid, 3, "step_completed")

        # ── Step 4: Baseline test ─────────────────────────────────────────
        _step_gate(4, "baseline-test")
        await set_status(CandidateStatus.BASELINE)
        _trace(rid, sid, 4, "step_started")
        baseline = await sandbox.run(
            f"cd {WORK_DIR} && {test_cmd} "
            f"--junitxml={ARTIFACTS_DIR}/baseline_junit.xml 2>&1",
            timeout=120,
            trusted=True,
        )
        baseline_output = baseline.stdout + baseline.stderr
        result.baseline_failed = baseline.exit_code != 0

        if not result.baseline_failed:
            await emit(rid, sid, "log", "⚠️ Baseline passes — issue not reproducible!")
            result.status = CandidateStatus.FAILED
            result.gate_failures.append("baseline_passed: issue not reproducible on this branch")
            _trace(rid, sid, 4, "step_completed", baseline_failed=False)
            return

        await emit(rid, sid, "log", "Baseline failed ✅ (expected). Running agent loop...")
        baseline_xml_result = await sandbox.run(
            f"cat {ARTIFACTS_DIR}/baseline_junit.xml 2>/dev/null || echo ''",
            timeout=15, trusted=True,
        )
        baseline_junit_xml = baseline_xml_result.stdout
        _trace(rid, sid, 4, "step_completed", baseline_failed=True)

        # ── Step 5: Agent loop (LLM-generated commands, NOT trusted) ─────
        _step_gate(5, "agent-loop")
        await set_status(CandidateStatus.PATCHING)
        _trace(rid, sid, 5, "step_started")
        # NOTE: sandbox.run calls inside agent loop do NOT pass trusted=True.
        # Each LLM-generated command is validated by the safety hook.
        steps, last_test_output = await run_agent_loop(
            sandbox=sandbox,
            strategy=strategy,
            issue_title=run.issue_title,
            issue_body=run.issue_body,
            test_cmd=test_cmd,
            run_id=rid,
            baseline_output=baseline_output,
        )
        result.steps = steps
        _trace(rid, sid, 5, "step_completed", agent_steps=len(steps))

        # ── Step 6: Final authoritative test run ──────────────────────────
        _step_gate(6, "final-test")
        await set_status(CandidateStatus.TESTING)
        _trace(rid, sid, 6, "step_started")
        final = await sandbox.run(
            f"cd {WORK_DIR} && {test_cmd} "
            f"--junitxml={ARTIFACTS_DIR}/final_junit.xml 2>&1",
            timeout=120,
            trusted=True,
        )
        final_output = final.stdout + final.stderr
        result.final_passed = final.exit_code == 0
        final_xml_result = await sandbox.run(
            f"cat {ARTIFACTS_DIR}/final_junit.xml 2>/dev/null || echo ''",
            timeout=15, trusted=True,
        )
        final_junit_xml = final_xml_result.stdout
        at_least_one_new_pass, no_regression, test_details = compare_test_results(
            baseline_output, final_output,
            baseline_junit_xml, final_junit_xml,
        )
        result.at_least_one_new_pass = at_least_one_new_pass
        result.no_regression = no_regression
        for detail in test_details:
            await emit(rid, sid, "log", detail)
        await emit(rid, sid, "log",
                   f"Final test exit={final.exit_code} ({'PASS' if result.final_passed else 'FAIL'})")
        _trace(rid, sid, 6, "step_completed", final_passed=result.final_passed)

        # ── Step 7: Diff collection + safety scan ─────────────────────────
        # This is the DESIGNED CRASH POINT. If INJECT_FAILURE_AT_STEP=7 is
        # set, _step_gate raises here. Recovery policy: log failure, mark
        # candidate FAILED, proceed to cleanup (step 10).
        _step_gate(7, "diff-and-safety-scan")
        _trace(rid, sid, 7, "step_started")
        try:
            stat = await sandbox.run(f"cd {WORK_DIR} && git diff --stat", timeout=15, trusted=True)
            diff = await sandbox.run(f"cd {WORK_DIR} && git diff", timeout=15, trusted=True)
            result.diff_stat = stat.stdout.strip()
            result.diff_text = diff.stdout[:8000]
            result.lines_changed = _count_diff_lines(diff.stdout)
            files_out = await sandbox.run(
                f"cd {WORK_DIR} && git diff --name-only", timeout=15, trusted=True
            )
            result.files_changed = [f.strip() for f in files_out.stdout.splitlines() if f.strip()]
            result.safety_flags = safety_scan(result.diff_text, result.files_changed)
            if result.safety_flags:
                await emit(rid, sid, "log", "Safety flags: " + " | ".join(result.safety_flags))
            _trace(rid, sid, 7, "step_completed", files_changed=len(result.files_changed))
        except RuntimeError as step7_err:
            # Record and apply recovery policy: log, mark failed, continue to cleanup.
            _trace(rid, sid, 7, "step_failed", error=str(step7_err),
                   policy="fresh", policy_reason="step 7 failed; cleanup and skip remaining steps")
            _trace(rid, sid, 7, "policy_applied", policy="fresh",
                   note="sandbox will be deleted in finally block")
            await emit(rid, sid, "log",
                       f"Step 7 failed ({step7_err}). Recovery policy: fresh (cleanup and mark failed).")
            result.gate_failures.append(f"step7_failed: {str(step7_err)[:200]}")
            result.status = CandidateStatus.FAILED
            return  # Skip steps 8–9; cleanup happens in finally

        # ── Step 8: Regression test (testfirst only) ──────────────────────
        _step_gate(8, "regression-test")
        _trace(rid, sid, 8, "step_started")
        if strategy.id == "testfirst":
            result.regression_test_passed = await _verify_regression_test(
                sandbox, steps, test_cmd, rid, sid
            )
            await emit(rid, sid, "log",
                       f"Regression test: {'✅ passes' if result.regression_test_passed else '❌ not verified'}")
        _trace(rid, sid, 8, "step_completed")

        # ── Step 9: Serve + verify ────────────────────────────────────────
        _step_gate(9, "serve-verify")
        _trace(rid, sid, 9, "step_started")
        if result.final_passed and start_cmd and app_port:
            await set_status(CandidateStatus.SERVING)
            await run_serve_verify(
                sandbox=sandbox,
                result=result,
                start_cmd=start_cmd,
                app_port=app_port,
                run_id=rid,
                strategy_id=sid,
                issue_title=run.issue_title,
                issue_body=run.issue_body,
                run_dir=f"runs/{rid}/{sid}",
            )
        _trace(rid, sid, 9, "step_completed")

        if result.final_passed:
            await set_status(CandidateStatus.PASSED)
        else:
            await set_status(CandidateStatus.FAILED)

    finally:
        # ── Step 10: Cleanup (always) ─────────────────────────────────────
        # Runs on success, failure, timeout, and CancelledError.
        # asyncio.shield prevents a CancelledError from skipping deletion.
        _trace(rid, sid, 10, "cleanup_started",
               sandbox_name=sandbox.name if sandbox else "none")
        if sandbox:
            try:
                try:
                    await sandbox.run(
                        f"cd {WORK_DIR} && git diff > {ARTIFACTS_DIR}/patch.diff 2>&1 || true",
                        timeout=15,
                        trusted=True,
                    )
                except (asyncio.CancelledError, Exception):
                    pass  # artifact save is best-effort
            finally:
                cleanup_task = asyncio.create_task(sandbox.delete())
                try:
                    await asyncio.shield(cleanup_task)
                    _trace(rid, sid, 10, "cleanup_completed",
                           sandbox_name=sandbox.name, result="deleted")
                except asyncio.CancelledError:
                    try:
                        await cleanup_task
                        _trace(rid, sid, 10, "cleanup_completed",
                               sandbox_name=sandbox.name, result="deleted-after-cancel")
                    except Exception as cleanup_error:
                        _trace(rid, sid, 10, "cleanup_failed",
                               sandbox_name=sandbox.name,
                               error=str(cleanup_error)[:200])
                        try:
                            await emit(rid, sid, "log",
                                       f"Sandbox cleanup raised an error: {cleanup_error}")
                        except Exception:
                            pass
                    raise
                except Exception as cleanup_error:
                    _trace(rid, sid, 10, "cleanup_failed",
                           sandbox_name=sandbox.name,
                           error=str(cleanup_error)[:200])
                    try:
                        await emit(rid, sid, "log",
                                   f"Sandbox cleanup raised an error: {cleanup_error}")
                    except Exception:
                        pass
        else:
            _trace(rid, sid, 10, "cleanup_skipped", reason="sandbox was never created")


async def _verify_regression_test(
    sandbox, steps, test_cmd: str, run_id: str, strategy_id: str
) -> bool:
    result = await sandbox.run(
        f"cd ~/work/app && python -m pytest -x -q -k 'regression' --tb=short 2>&1 || true",
        timeout=60,
        trusted=True,
    )
    output = result.stdout + result.stderr
    return "passed" in output.lower() and result.exit_code == 0


def _count_diff_lines(diff: str) -> int:
    count = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            count += 1
        elif line.startswith("-") and not line.startswith("---"):
            count += 1
    return count


def _get_install_cmd(repo: str) -> str:
    return "pip install -e '.[test]' -q 2>&1 || pip install -e . -q 2>&1"

def _get_test_cmd(repo: str) -> str:
    return "python -m pytest -x -q --tb=short"

def _get_start_cmd(repo: str) -> str:
    return "python app.py"

def _get_app_port(repo: str) -> int:
    return 5000
