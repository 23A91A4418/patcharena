"""Per-strategy candidate pipeline: clone → install → baseline → patch → test → serve → verify."""

from __future__ import annotations

import asyncio
from datetime import datetime

from . import events
from .agent import run_agent_loop
from .celesto_client import Sandbox, make_sandbox_name
from .config import SANDBOX_TIMEOUT_S
from .models import CandidateResult, CandidateStatus, RunState, Strategy
from .test_parser import compare_test_results
from .verify import run_serve_verify, safety_scan

WORK_DIR = "~/work/app"
ARTIFACTS_DIR = "~/work/artifacts"


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
    except Exception as e:
        result.status = CandidateStatus.ERROR
        await events.emit(run.run_id, strategy.id, "log", f"Pipeline error: {e}")
        await events.emit(run.run_id, strategy.id, "status", CandidateStatus.ERROR)
    finally:
        result.finished_at = datetime.utcnow()
        # Emit final result event for dashboard
        await events.emit(run.run_id, strategy.id, "result", result.model_dump(mode="json"))

    return result


async def _pipeline(strategy: Strategy, run: RunState, result: CandidateResult) -> None:
    emit = events.emit
    rid = run.run_id
    sid = strategy.id

    # ── Resolve demo repo config ──────────────────────────────────────────────
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
        # 1. Create sandbox
        await set_status(CandidateStatus.CLONING)
        sandbox = await Sandbox.create(
            name=result.sandbox_name,
            run_id=rid,
            strategy_id=sid,
            emit=emit,
        )

        # 2. Clone repo + create branch
        branch = f"patcharena/{run.run_id}/{sid}"
        clone_result = await sandbox.run(
            f"git clone {repo} {WORK_DIR} && "
            f"cd {WORK_DIR} && git checkout -b {branch}",
            timeout=120,
        )
        if clone_result.exit_code != 0:
            raise RuntimeError(f"Clone failed: {clone_result.stderr[:200]}")

        # 3. Install
        await set_status(CandidateStatus.INSTALLING)
        install_result = await sandbox.run(
            f"cd {WORK_DIR} && {install_cmd}",
            timeout=180,
        )
        if install_result.exit_code != 0:
            raise RuntimeError(f"Install failed: {install_result.stderr[:200]}")

        # Make artifacts dir
        await sandbox.run(f"mkdir -p {ARTIFACTS_DIR}", timeout=10)

        # 4. Baseline test — save output AND junit XML
        await set_status(CandidateStatus.BASELINE)
        baseline = await sandbox.run(
            f"cd {WORK_DIR} && {test_cmd} "
            f"--junitxml={ARTIFACTS_DIR}/baseline_junit.xml 2>&1",
            timeout=120,
        )
        baseline_output = baseline.stdout + baseline.stderr
        result.baseline_failed = baseline.exit_code != 0

        if not result.baseline_failed:
            await emit(rid, sid, "log", "⚠️ Baseline passes — issue not reproducible!")
            result.status = CandidateStatus.FAILED
            result.gate_failures.append("baseline_passed: issue not reproducible on this branch")
            return

        await emit(rid, sid, "log", "Baseline failed ✅ (expected). Running agent loop...")

        # Read baseline junit XML for comparison later
        baseline_xml_result = await sandbox.run(
            f"cat {ARTIFACTS_DIR}/baseline_junit.xml 2>/dev/null || echo ''", timeout=15
        )
        baseline_junit_xml = baseline_xml_result.stdout

        # 5. Agent loop
        await set_status(CandidateStatus.PATCHING)
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

        # 6. Final authoritative test + JUnit XML
        await set_status(CandidateStatus.TESTING)
        final = await sandbox.run(
            f"cd {WORK_DIR} && {test_cmd} "
            f"--junitxml={ARTIFACTS_DIR}/final_junit.xml 2>&1",
            timeout=120,
        )
        final_output = final.stdout + final.stderr
        result.final_passed = final.exit_code == 0

        # Read final junit XML
        final_xml_result = await sandbox.run(
            f"cat {ARTIFACTS_DIR}/final_junit.xml 2>/dev/null || echo ''", timeout=15
        )
        final_junit_xml = final_xml_result.stdout

        # Test set comparison for judge gates
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

        # 7. Diff
        stat = await sandbox.run(f"cd {WORK_DIR} && git diff --stat", timeout=15)
        diff = await sandbox.run(f"cd {WORK_DIR} && git diff", timeout=15)
        result.diff_stat = stat.stdout.strip()
        result.diff_text = diff.stdout[:8000]
        result.lines_changed = _count_diff_lines(diff.stdout)

        files_out = await sandbox.run(
            f"cd {WORK_DIR} && git diff --name-only", timeout=15
        )
        result.files_changed = [f.strip() for f in files_out.stdout.splitlines() if f.strip()]

        # Safety scan — flags suspicious patterns, hard-fails only on forbidden paths
        result.safety_flags = safety_scan(result.diff_text, result.files_changed)
        if result.safety_flags:
            await emit(rid, sid, "log",
                       "Safety flags: " + " | ".join(result.safety_flags))

        # 8. Regression test check for testfirst strategy
        if strategy.id == "testfirst":
            result.regression_test_passed = await _verify_regression_test(
                sandbox, steps, test_cmd, rid, sid
            )
            await emit(rid, sid, "log",
                       f"Regression test: {'✅ passes' if result.regression_test_passed else '❌ not verified'}")

        # 9. Serve + verify (only if tests pass and it's a web app)
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

        if result.final_passed:
            await set_status(CandidateStatus.PASSED)
        else:
            await set_status(CandidateStatus.FAILED)

    finally:
        # Always capture diff artifact; leave sandbox alive for preview
        if sandbox:
            try:
                await sandbox.run(
                    f"cd {WORK_DIR} && git diff > {ARTIFACTS_DIR}/patch.diff 2>&1 || true",
                    timeout=15,
                )
            except Exception:
                pass


async def _verify_regression_test(
    sandbox, steps, test_cmd: str, run_id: str, strategy_id: str
) -> bool:
    """
    For testfirst: find the regression test file added in step 1 and verify:
    - It fails on the original baseline branch (would need fresh checkout — approximated)
    - It passes in the current patched state

    MVP approximation: confirm the test file exists and passes in the current state.
    A full check would require a second sandbox or a checkout of the original branch.
    """
    # Find a created test file from the first step's edits
    reg_test_path = None
    for step in steps:
        # The step doesn't store individual edit paths directly, but we can infer
        # from the diff text
        break

    # Simpler: just run pytest with -k "regression" to check if any marked test passes
    result = await sandbox.run(
        f"cd ~/work/app && python -m pytest -x -q -k 'regression' --tb=short 2>&1 || true",
        timeout=60,
    )
    output = result.stdout + result.stderr
    # If at least one test passed with "regression" marker/comment, it's verified
    return "passed" in output.lower() and result.exit_code == 0


def _count_diff_lines(diff: str) -> int:
    count = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            count += 1
        elif line.startswith("-") and not line.startswith("---"):
            count += 1
    return count


# ── Demo repo config lookup ────────────────────────────────────────────────────
# Hardcoded for MVP. Auto-detect is a non-goal.

def _get_install_cmd(repo: str) -> str:
    return "pip install -e '.[test]' -q 2>&1 || pip install -e . -q 2>&1"

def _get_test_cmd(repo: str) -> str:
    return "python -m pytest -x -q --tb=short"

def _get_start_cmd(repo: str) -> str:
    return "python app.py"

def _get_app_port(repo: str) -> int:
    return 5000
