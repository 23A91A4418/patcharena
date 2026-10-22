
"""Integration tests for Celesto — use an existing cloud computer."""

from __future__ import annotations

import os

import pytest

from backend.celesto_client import Sandbox


def existing_sandbox() -> Sandbox:
    """Build a client for an existing Celesto cloud computer."""
    computer_id = os.environ.get("CELESTO_TEST_COMPUTER_ID")
    if not computer_id:
        pytest.skip(
            "Set CELESTO_TEST_COMPUTER_ID to an existing cloud computer ID."
        )

    return Sandbox(name=computer_id)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_create_run_write_read_delete():
    """Test execution and file operations without deleting the shared computer."""
    sb = existing_sandbox()

    result = await sb.run("echo hello from sandbox")
    assert result.exit_code == 0
    assert "hello" in result.stdout

    path = "/tmp/patcharena_test.txt"
    await sb.write_file(path, "integration test content")
    content = await sb.read_file(path)
    assert "integration test content" in content


@pytest.mark.slow
@pytest.mark.asyncio
async def test_non_zero_exit_does_not_raise():
    """A failing command returns its exit code without raising."""
    sb = existing_sandbox()

    result = await sb.run("exit 42", timeout=10)
    assert result.exit_code == 42
