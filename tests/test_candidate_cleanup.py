import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend import candidate
from backend.models import (
    CandidateResult,
    CandidateStatus,
    RunState,
    Strategy,
)


@pytest.fixture
def pipeline_inputs():
    strategy = Strategy(
        id="minimal",
        name="Minimal",
        description="Cleanup test",
        instructions="Test sandbox lifecycle",
    )

    result = CandidateResult(
        strategy_id="minimal",
        sandbox_name="sbx-test0001",
    )

    run = RunState(
        run_id="test-run-001",
        repo="https://example.com/test-repo.git",
        issue="Test issue",
        issue_title="Cleanup test",
        issue_body="Test cleanup behavior",
        strategy_ids=["minimal"],
        candidates={"minimal": result},
    )

    return strategy, run, result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    ["success", "exception", "timeout", "cancellation"],
)
async def test_run_candidate_cleanup_is_attempted(
    monkeypatch, pipeline_inputs, outcome
):
    strategy, run, result = pipeline_inputs
    cleanup_called = asyncio.Event()

    async def fake_pipeline(strategy_arg, run_arg, result_arg):
        assert strategy_arg.id == strategy.id
        assert run_arg.run_id == run.run_id

        try:
            if outcome == "success":
                result_arg.status = CandidateStatus.PASSED
                return

            if outcome == "exception":
                raise RuntimeError("simulated pipeline failure")

            if outcome == "timeout":
                await asyncio.sleep(10)

            if outcome == "cancellation":
                await asyncio.Event().wait()

        finally:
            # This test double represents the pipeline's cleanup attempt.
            cleanup_called.set()

    monkeypatch.setattr(candidate, "_pipeline", fake_pipeline)
    monkeypatch.setattr(candidate, "SANDBOX_TIMEOUT_S", 0.05)
    monkeypatch.setattr(candidate.events, "emit", AsyncMock())

    task = asyncio.create_task(
        candidate.run_candidate(strategy, run)
    )

    if outcome == "cancellation":
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task

    assert cleanup_called.is_set()


@pytest.mark.asyncio
async def test_real_pipeline_deletes_sandbox_after_execution_failure(
    monkeypatch, pipeline_inputs
):
    strategy, run, result = pipeline_inputs

    fake_sandbox = SimpleNamespace(
        name="cmp-test-cleanup",
        run=AsyncMock(
            side_effect=RuntimeError("simulated sandbox execution failure")
        ),
        delete=AsyncMock(),
    )

    async def fake_create(**kwargs):
        return fake_sandbox

    monkeypatch.setattr(candidate.Sandbox, "create", fake_create)
    monkeypatch.setattr(candidate.events, "emit", AsyncMock())

    with pytest.raises(RuntimeError, match="simulated sandbox execution failure"):
        await candidate._pipeline(strategy, run, result)

    fake_sandbox.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_pipeline_attempts_delete_on_cancellation(
    monkeypatch, pipeline_inputs
):
    strategy, run, result = pipeline_inputs
    delete_started = asyncio.Event()
    allow_delete = asyncio.Event()

    class FakeSandbox:
        name = "cmp-test-cancel"

        async def run(self, *args, **kwargs):
            raise asyncio.CancelledError()

        async def delete(self):
            delete_started.set()
            await allow_delete.wait()

    fake_sandbox = FakeSandbox()

    async def fake_create(**kwargs):
        return fake_sandbox

    monkeypatch.setattr(candidate.Sandbox, "create", fake_create)
    monkeypatch.setattr(candidate.events, "emit", AsyncMock())

    task = asyncio.create_task(
        candidate._pipeline(strategy, run, result)
    )

    await delete_started.wait()
    assert not task.done()

    allow_delete.set()

    with pytest.raises(asyncio.CancelledError):
        await task
