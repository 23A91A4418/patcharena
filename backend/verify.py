"""Preview serving, health check, screenshot, and safety scan."""

from __future__ import annotations

import asyncio
import os

import httpx

from . import events
from . import llm
from .models import CandidateResult

WORK_DIR = "~/work/app"
ARTIFACTS_DIR = "~/work/artifacts"


async def run_serve_verify(
    sandbox,
    result: CandidateResult,
    start_cmd: str,
    app_port: int,
    run_id: str,
    strategy_id: str,
    issue_title: str,
    issue_body: str,
    run_dir: str,
) -> None:
    """Start the app, publish port, take screenshot, run vision verify."""

    # 1. Start app in background
    await sandbox.run(
        f"cd {WORK_DIR} && nohup {start_cmd} > {ARTIFACTS_DIR}/server.log 2>&1 &",
        timeout=15,
    )

    # 2. Health check loop (30s)
    healthy = False
    for _ in range(30):
        check = await sandbox.run(
            f"curl -sf http://localhost:{app_port}/ --max-time 2 -o /dev/null",
            timeout=10,
        )
        if check.exit_code == 0:
            healthy = True
            break
        await asyncio.sleep(1)

    if not healthy:
        await events.emit(run_id, strategy_id, "log",
                          "⚠️ App did not become healthy within 30s")
        return

    await events.emit(run_id, strategy_id, "log", "App is healthy ✅")

    # 3. Publish port
    try:
        preview_url = await sandbox.publish_port(app_port)
        result.preview_url = preview_url
        await events.emit(run_id, strategy_id, "log", f"Preview URL: {preview_url}")
    except Exception as e:
        await events.emit(run_id, strategy_id, "log", f"⚠️ Could not publish port: {e}")
        return

    # 4. HTTP 200 check from orchestrator
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(preview_url)
            if resp.status_code == 200:
                await events.emit(run_id, strategy_id, "log",
                                  f"HTTP 200 from preview URL ✅")
            else:
                await events.emit(run_id, strategy_id, "log",
                                  f"Preview returned {resp.status_code} ⚠️")
    except Exception as e:
        await events.emit(run_id, strategy_id, "log", f"Preview fetch failed: {e}")

    # 5. Screenshot via Playwright (fallback if no native celesto screenshot)
    os.makedirs(run_dir, exist_ok=True)
    shot_path = os.path.join(run_dir, "shot.png")
    screenshot_ok = await _take_screenshot(preview_url, shot_path, run_id, strategy_id)

    if screenshot_ok:
        result.screenshot_path = shot_path

        # 6. Vision LLM check
        await _vision_verify(
            result=result,
            shot_path=shot_path,
            issue_title=issue_title,
            run_id=run_id,
            strategy_id=strategy_id,
        )


async def _take_screenshot(url: str, out_path: str, run_id: str, strategy_id: str) -> bool:
    """Take a screenshot using Playwright."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "python", "-c",
            f"""
import asyncio
from playwright.async_api import async_playwright

async def shot():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto('{url}', timeout=15000)
        await asyncio.sleep(2)
        await page.screenshot(path='{out_path}', full_page=True)
        await browser.close()

asyncio.run(shot())
""",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0:
            await events.emit(run_id, strategy_id, "log", f"Screenshot saved ✅")
            return True
        else:
            await events.emit(run_id, strategy_id, "log",
                              f"Screenshot failed: {stderr.decode()[:200]}")
            return False
    except Exception as e:
        await events.emit(run_id, strategy_id, "log", f"Screenshot error: {e}")
        return False


async def _vision_verify(
    result: CandidateResult,
    shot_path: str,
    issue_title: str,
    run_id: str,
    strategy_id: str,
) -> None:
    """Ask an LLM with vision to verify the bug is fixed."""
    prompt = f"""You are verifying that a bug fix is visible in a web app screenshot.

Issue: {issue_title}

Look at the screenshot. Is the bug described in the issue visually fixed?
Return ONLY valid JSON:
{{"fixed": true/false, "evidence": "one sentence describing what you see"}}
"""
    try:
        resp = await llm.json_call(prompt, image_path=shot_path)
        result.browser_verified = bool(resp.get("fixed", False))
        evidence = resp.get("evidence", "")
        await events.emit(run_id, strategy_id, "log",
                          f"Vision check: fixed={result.browser_verified} — {evidence}")
    except Exception as e:
        await events.emit(run_id, strategy_id, "log", f"Vision verify error: {e}")


def safety_scan(diff_text: str, files_changed: list[str]) -> list[str]:
    """
    Flag suspicious patterns in a diff. Returns a list of warning strings.
    Hard-fail only happens on forbidden paths (handled in edits.py).
    """
    flags = []
    sensitive_patterns = [
        ("requests.", "new HTTP request"),
        ("fetch(", "new fetch call"),
        ("subprocess.", "shell execution"),
        ("os.system(", "os.system call"),
        ("curl ", "curl command"),
        ("eval(", "eval usage"),
    ]
    ci_patterns = [".github/", ".travis.yml", ".circleci/", "Jenkinsfile"]

    for pattern, label in sensitive_patterns:
        if pattern in diff_text:
            flags.append(f"⚠️ Added {label}")

    for ci in ci_patterns:
        for f in files_changed:
            if ci in f:
                flags.append(f"⚠️ Touched CI file: {f}")

    return flags
