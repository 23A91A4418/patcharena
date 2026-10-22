"""Unit tests for edits.py — covers 8+ cases per spec."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

# We mock the sandbox to avoid needing a real Celesto sandbox
from backend.edits import apply_edits, _is_forbidden
from backend.models import EditSpec


def make_sandbox(files: dict[str, str]):
    """Create a mock sandbox with specified file contents."""
    sb = MagicMock()
    sb.read_file = AsyncMock(side_effect=lambda path: _lookup(files, path))
    sb.write_file = AsyncMock(return_value=None)
    return sb


def _lookup(files: dict, path: str) -> str:
    # normalize path
    for k, v in files.items():
        if k in path or path in k:
            return v
    raise FileNotFoundError(f"Mock: no file {path}")


# ── is_forbidden tests ────────────────────────────────────────────────────────

def test_forbidden_dotenv():
    assert _is_forbidden(".env") is True

def test_forbidden_pem():
    assert _is_forbidden("certs/server.pem") is True

def test_forbidden_github():
    assert _is_forbidden(".github/workflows/ci.yml") is True

def test_forbidden_traversal():
    assert _is_forbidden("../../etc/passwd") is True

def test_allowed_normal_path():
    assert _is_forbidden("src/app.py") is False


# ── apply_edits tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exact_match():
    sb = make_sandbox({"src/app.py": "x = 1\ny = 2\n"})
    edits = [EditSpec(path="src/app.py", search="x = 1", replace="x = 99")]
    results = await apply_edits(sb, edits)
    assert results[0].success
    # Verify write was called with replaced content
    sb.write_file.assert_called_once()
    written = sb.write_file.call_args[0][1]
    assert "x = 99" in written


@pytest.mark.asyncio
async def test_no_match():
    sb = make_sandbox({"src/app.py": "x = 1\n"})
    edits = [EditSpec(path="src/app.py", search="not there", replace="foo")]
    results = await apply_edits(sb, edits)
    assert not results[0].success
    assert "not found" in results[0].error


@pytest.mark.asyncio
async def test_multi_match():
    sb = make_sandbox({"src/app.py": "x = 1\nx = 1\n"})
    edits = [EditSpec(path="src/app.py", search="x = 1", replace="x = 2")]
    results = await apply_edits(sb, edits)
    assert not results[0].success
    assert "2 times" in results[0].error


@pytest.mark.asyncio
async def test_create_new_file():
    sb = make_sandbox({})
    sb.write_file = AsyncMock()
    edits = [EditSpec(path="tests/test_new.py", create=True, content="def test_foo(): pass")]
    results = await apply_edits(sb, edits)
    assert results[0].success
    sb.write_file.assert_called_once()


@pytest.mark.asyncio
async def test_forbidden_path_rejected():
    sb = make_sandbox({})
    edits = [EditSpec(path=".env", search="SECRET", replace="")]
    results = await apply_edits(sb, edits)
    assert not results[0].success
    assert "Forbidden" in results[0].error


@pytest.mark.asyncio
async def test_crlf_normalization():
    sb = make_sandbox({"src/app.py": "x = 1\r\ny = 2\r\n"})
    # Search uses LF — should still match after normalization
    edits = [EditSpec(path="src/app.py", search="x = 1\ny = 2", replace="x = 10\ny = 20")]
    results = await apply_edits(sb, edits)
    assert results[0].success


@pytest.mark.asyncio
async def test_file_not_found():
    sb = MagicMock()
    sb.read_file = AsyncMock(side_effect=FileNotFoundError("not found"))
    edits = [EditSpec(path="src/missing.py", search="x", replace="y")]
    results = await apply_edits(sb, edits)
    assert not results[0].success
    assert "not found" in results[0].error.lower()


@pytest.mark.asyncio
async def test_create_missing_content():
    sb = make_sandbox({})
    edits = [EditSpec(path="new.py", create=True, content=None)]
    results = await apply_edits(sb, edits)
    assert not results[0].success
