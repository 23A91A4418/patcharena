
"""Celesto Cloud sandbox wrapper for PatchArena."""

from __future__ import annotations

import asyncio
import base64
import os
import shlex
import shutil
import time
from dataclasses import dataclass, field

from .config import CELESTO_API_KEY, SANDBOX_PREFIX, redact
from .models import ExecResult
from .safety import validate_command

DEFAULT_CMD_TIMEOUT = 120
DEFAULT_RETRIES = 1
PUBLISH_TIMEOUT = 30


class CommandBlockedError(RuntimeError):
    """Raised when a command is blocked by the pre-execution safety hook."""


@dataclass
class Sandbox:
    name: str
    run_id: str = ""
    strategy_id: str = ""
    _emit: object = field(default=None, repr=False)

    @classmethod
    async def create(
        cls,
        name: str,
        run_id: str = "",
        strategy_id: str = "",
        emit=None,
        template: str = "coding-agent",
        disk_mb: int = 10240,
    ) -> "Sandbox":
        # Celesto Cloud manages its own computer configuration.
        sb = cls(
            name=name,
            run_id=run_id,
            strategy_id=strategy_id,
            _emit=emit,
        )

        args = ["computer", "create", "--cloud"]

        if template and template != "coding-agent":
            await sb._log(
                f"Note: Celesto Cloud manages its configuration; "
                f"template '{template}' is not applied."
            )

        stdout, stderr, rc = await sb._celesto(args, timeout=150)

        if rc != 0:
            raise RuntimeError(
                "Celesto cloud computer creation failed: "
                f"{(stderr or stdout)[:500]}"
            )

        created_id = _extract_computer_id(stdout)

        if created_id:
            sb.name = created_id
        else:
            await sb._log(
                "Warning: Celesto did not return a recognizable computer ID. "
                "The requested name may not be the cloud computer ID."
            )

        await sb._log(f"Cloud computer created: {sb.name}")
        return sb

    async def run(
        self,
        cmd: str,
        timeout: int = DEFAULT_CMD_TIMEOUT,
        env: dict[str, str] | None = None,
        trusted: bool = False,
    ) -> ExecResult:
        """
        Execute a shell command inside the sandbox.

        Parameters
        ----------
        cmd:     Shell command to run.
        timeout: Seconds to wait for the command to complete.
        env:     Extra environment variables to inject (values are not logged).
        trusted: If True, skip safety-pattern checks. Only set this for
                 application-owned commands (git, pip, pytest, etc.), never
                 for text that originates from the LLM or user input.

        Raises
        ------
        CommandBlockedError: if the safety hook blocks the command.
        """
        decision = validate_command(
            cmd,
            sandbox_name=self.name,
            run_id=self.run_id,
            candidate_id=self.strategy_id,
            trusted=trusted,
        )
        if not decision.allowed:
            raise CommandBlockedError(
                f"Command blocked by safety hook: {decision.reason}\n"
                f"Command summary (first 200 chars): {cmd[:200]}"
            )

        started = time.monotonic()
        shell_cmd = cmd

        if env:
            assignments = " ".join(
                f"{key}={shlex.quote(value)}"
                for key, value in env.items()
            )
            shell_cmd = f"export {assignments}; {cmd}"

        stdout, stderr, rc = await self._celesto(
            [
                "computer",
                "exec",
                "--cloud",
                "--timeout",
                str(max(1, timeout)),
                self.name,
                "--",
                "bash",
                "-lc",
                shell_cmd,
            ],
            timeout=timeout + 15,
        )

        duration = time.monotonic() - started

        result = ExecResult(
            stdout=_truncate_lines(stdout, 200),
            stderr=_truncate_lines(stderr, 80),
            exit_code=rc,
            duration_s=round(duration, 2),
        )

        await self._log(
            f"$ {redact(cmd)[:120]} -> exit={rc} ({duration:.1f}s)"
        )
        return result

    async def write_file(self, path: str, content: str) -> None:
        encoded = base64.b64encode(
            content.encode("utf-8")
        ).decode("ascii")

        result = await self.run(
            f"mkdir -p -- {shlex.quote(os.path.dirname(path) or '.')}"
            f" && printf '%s' {shlex.quote(encoded)}"
            f" | base64 -d > {shlex.quote(path)}",
            timeout=30,
        )

        if result.exit_code != 0:
            raise RuntimeError(
                f"write_file failed: path={path}; {result.stderr[:200]}"
            )

    async def read_file(self, path: str) -> str:
        result = await self.run(
            f"cat -- {shlex.quote(path)}",
            timeout=30,
        )

        if result.exit_code != 0:
            raise FileNotFoundError(
                f"read_file failed: path={path}; {result.stderr[:200]}"
            )

        return result.stdout

    async def publish_port(self, port: int) -> str:
        stdout, stderr, rc = await self._celesto(
            [
                "computer",
                "port",
                "publish",
                self.name,
                "--port",
                str(port),
            ],
            timeout=PUBLISH_TIMEOUT,
        )

        if rc != 0:
            raise RuntimeError(
                f"Port publishing failed: {(stderr or stdout)[:300]}"
            )

        for line in (stdout + "\n" + stderr).splitlines():
            for part in line.split():
                if part.startswith(("http://", "https://")):
                    return part.rstrip(".,)")

        raise RuntimeError(f"No preview URL found: {stdout[:300]}")

    async def stop(self) -> None:
        stdout, stderr, rc = await self._celesto(
            ["computer", "stop", "--cloud", self.name],
            timeout=60,
        )

        if rc != 0:
            raise RuntimeError(f"Stop failed: {(stderr or stdout)[:300]}")

        await self._log(f"Sandbox {self.name} stopped")

    async def start(self) -> None:
        stdout, stderr, rc = await self._celesto(
            ["computer", "start", "--cloud", self.name],
            timeout=90,
        )

        if rc != 0:
            raise RuntimeError(f"Start failed: {(stderr or stdout)[:300]}")

        await asyncio.sleep(3)
        await self._log(f"Sandbox {self.name} started")

    async def delete(self) -> None:
        """Delete this cloud sandbox; raise if deletion fails."""
        stdout, stderr, rc = await self._celesto(
            ["computer", "delete", "--cloud", "--yes", self.name],
            timeout=60,
        )

        if rc != 0:
            message = (stderr or stdout or "Unknown Celesto error")[:300]

            await self._log(
                f"ERROR: failed to delete sandbox {self.name}: {message}"
            )

            raise RuntimeError(
                f"Failed to delete sandbox {self.name}: {message}"
            )

        await self._log(f"Sandbox {self.name} deleted")

    async def _celesto(
        self,
        args: list[str],
        timeout: int = 60,
        env: dict[str, str] | None = None,
        _retry: int = 0,
    ) -> tuple[str, str, int]:
        executable = shutil.which("celesto")

        if not executable:
            raise RuntimeError(
                "Celesto CLI not found. Activate the Ubuntu "
                "patcharena-venv and install Celesto there."
            )

        proc_env = os.environ.copy()

        if CELESTO_API_KEY:
            proc_env["CELESTO_API_KEY"] = CELESTO_API_KEY

        if env:
            proc_env.update(env)

        try:
            proc = await asyncio.create_subprocess_exec(
                executable,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=proc_env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # Prevent the local Celesto CLI subprocess from being
                # left running after its timeout.
                proc.kill()
                await proc.communicate()
                raise

            return (
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
                proc.returncode,
            )

        except (asyncio.TimeoutError, OSError) as exc:
            if _retry < DEFAULT_RETRIES:
                await self._log(
                    f"Celesto transport error: {exc}; retrying"
                )
                await asyncio.sleep(2)
                return await self._celesto(
                    args, timeout, env, _retry + 1
                )
            raise

    async def _log(self, msg: str) -> None:
        if self._emit:
            await self._emit(
                self.run_id,
                self.strategy_id,
                "log",
                redact(msg),
            )


def _extract_computer_id(output: str) -> str | None:
    """Extract a cloud computer ID from common CLI output formats."""
    import re

    match = re.search(r"\bcmp_[A-Za-z0-9_-]+\b", output)

    if match:
        return match.group(0)

    return None


def _truncate_lines(text: str, max_lines: int) -> str:
    lines = [line[:2000] for line in text.splitlines()]

    if len(lines) > max_lines:
        lines = (
            [f"[...truncated {len(lines) - max_lines} lines...]"]
            + lines[-max_lines:]
        )

    return "\n".join(lines)


def make_sandbox_name(run_id: str, strategy_id: str) -> str:
    return f"{SANDBOX_PREFIX}-{run_id[:8]}-{strategy_id}"
