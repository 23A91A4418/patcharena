import pytest

from backend.celesto_client import Sandbox


@pytest.mark.asyncio
async def test_delete_success(monkeypatch):
    sandbox = Sandbox(name="cmp_test")

    async def fake_celesto(args, timeout=60, env=None, _retry=0):
        assert args == [
            "computer", "delete", "--cloud", "--yes", "cmp_test"
        ]
        return "deleted", "", 0

    monkeypatch.setattr(sandbox, "_celesto", fake_celesto)

    await sandbox.delete()


@pytest.mark.asyncio
async def test_delete_failure_raises(monkeypatch):
    sandbox = Sandbox(name="cmp_test")

    async def fake_celesto(args, timeout=60, env=None, _retry=0):
        return "", "permission denied", 1

    monkeypatch.setattr(sandbox, "_celesto", fake_celesto)

    with pytest.raises(RuntimeError, match="Failed to delete sandbox"):
        await sandbox.delete()
