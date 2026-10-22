"""LLM-powered agent loop that iteratively applies patches."""

from __future__ import annotations

import re

from . import events
from . import llm
from .config import MAX_AGENT_STEPS, redact
from .edits import apply_edits
from .models import AgentResponse, EditSpec, StepRecord, Strategy


WORK_DIR = "~/work/app"


def _build_patch_prompt(
    issue_title: str,
    issue_body: str,
    strategy: Strategy,
    repo_tree: str,
    file_contents: dict[str, str],
    last_test_output: str,
    apply_errors: list[str],
    step: int,
) -> str:
    files_section = "\n\n".join(
        f"### File: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    errors_section = ""
    if apply_errors:
        errors_section = f"\n\n## Edit Errors from Previous Step\n" + "\n".join(
            f"- {e}" for e in apply_errors
        )

    return f"""You are fixing a GitHub issue. Return ONLY valid JSON, no markdown, no explanation outside the JSON.

## Issue
Title: {issue_title}
{issue_body[:1500]}

## Strategy: {strategy.name}
{strategy.instructions}

## Step {step} of {MAX_AGENT_STEPS}

## Repository Tree
```
{repo_tree[:3000]}
```

## Relevant File Contents
{files_section}

## Last Test Output (last 80 lines)
```
{last_test_output[-3000:]}
```
{errors_section}

## Instructions
- Return JSON only with this exact shape:
{{
  "reasoning": "brief explanation of what you are changing and why",
  "edits": [
    {{"path": "relative/path/to/file.py", "search": "exact text to replace", "replace": "new text"}},
    {{"path": "tests/test_new.py", "create": true, "content": "full file content"}}
  ]
}}
- "search" must be copied EXACTLY from the file content provided — whitespace, indentation, everything.
- Make the minimum number of edits needed for strategy: {strategy.name}
- NEVER edit .github/, .env*, lockfiles, *.pem, or CI files
- NEVER claim tests pass — the tests will be run independently
- If the previous edits had errors, fix them in this step
"""


async def run_agent_loop(
    sandbox,
    strategy: Strategy,
    issue_title: str,
    issue_body: str,
    test_cmd: str,
    run_id: str,
    baseline_output: str,
) -> tuple[list[StepRecord], str]:
    """
    Run the patch-apply-test agent loop.
    Returns (steps, last_test_output).
    """
    steps: list[StepRecord] = []
    last_test_output = baseline_output
    apply_errors: list[str] = []

    for step in range(1, MAX_AGENT_STEPS + 1):
        await events.emit(run_id, strategy.id, "log", f"Agent step {step}/{MAX_AGENT_STEPS}")

        # Gather context
        repo_tree = await _get_repo_tree(sandbox)
        file_contents = await _get_relevant_files(sandbox, issue_title, issue_body, last_test_output)

        # Prompt LLM
        prompt = _build_patch_prompt(
            issue_title=issue_title,
            issue_body=issue_body,
            strategy=strategy,
            repo_tree=repo_tree,
            file_contents=file_contents,
            last_test_output=last_test_output,
            apply_errors=apply_errors,
            step=step,
        )

        try:
            resp_dict = await llm.json_call(prompt)
            agent_resp = AgentResponse(
                reasoning=resp_dict.get("reasoning", ""),
                edits=[EditSpec(**e) for e in resp_dict.get("edits", [])],
            )
        except Exception as e:
            await events.emit(run_id, strategy.id, "log", f"LLM error at step {step}: {e}")
            apply_errors = [str(e)]
            continue

        await events.emit(run_id, strategy.id, "log",
                          f"Reasoning: {agent_resp.reasoning[:200]}")

        # Apply edits
        edit_results = await apply_edits(sandbox, agent_resp.edits)
        apply_errors = [r.error for r in edit_results if not r.success]
        edits_ok = sum(1 for r in edit_results if r.success)

        for r in edit_results:
            symbol = "✅" if r.success else "❌"
            await events.emit(run_id, strategy.id, "log",
                              f"{symbol} Edit {r.path}: {r.error or 'applied'}")

        # Run tests
        test_result = await sandbox.run(
            f"cd {WORK_DIR} && {test_cmd} 2>&1",
            timeout=120,
        )
        last_test_output = test_result.stdout + "\n" + test_result.stderr

        step_record = StepRecord(
            step_no=step,
            edits_applied=edits_ok,
            apply_errors=apply_errors,
            test_exit_code=test_result.exit_code,
            test_summary=_tail(last_test_output, 10),
        )
        steps.append(step_record)

        await events.emit(run_id, strategy.id, "step", {
            "step": step,
            "test_exit_code": test_result.exit_code,
            "edits_applied": edits_ok,
            "apply_errors": apply_errors,
        })

        if test_result.exit_code == 0 and not apply_errors:
            await events.emit(run_id, strategy.id, "log", "✅ Tests passing!")
            break

    return steps, last_test_output


async def _get_repo_tree(sandbox) -> str:
    result = await sandbox.run(
        f"find {WORK_DIR} -not -path '*/.*' -not -name '*.pyc' "
        f"| head -200 | sed 's|{WORK_DIR}/||'",
        timeout=20,
    )
    return result.stdout


async def _get_relevant_files(
    sandbox,
    issue_title: str,
    issue_body: str,
    test_output: str,
    max_files: int = 5,
) -> dict[str, str]:
    """Heuristically pick the most relevant files to include in the prompt."""
    candidates: list[str] = []

    # Files named in issue text (look for .py references)
    for text in [issue_title, issue_body]:
        for match in re.findall(r'[\w/]+\.py', text):
            candidates.append(match)

    # Files in failing test tracebacks
    for match in re.findall(r'(?:FAILED|ERROR|File ")[^\s"]+\.py', test_output):
        clean = match.replace("FAILED ", "").replace('File "', "").strip()
        candidates.append(clean)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    # Add main source files if we need more
    if len(unique) < max_files:
        ls_result = await sandbox.run(
            f"find {WORK_DIR}/src {WORK_DIR}/app {WORK_DIR} "
            f"-maxdepth 2 -name '*.py' -not -path '*/.*' 2>/dev/null | head -20",
            timeout=15,
        )
        for line in ls_result.stdout.splitlines():
            fname = line.strip().split("/")[-1]
            if fname not in seen:
                seen.add(fname)
                unique.append(line.strip().replace(WORK_DIR + "/", ""))

    file_contents = {}
    for fpath in unique[:max_files]:
        full = f"{WORK_DIR}/{fpath}" if not fpath.startswith("/") and not fpath.startswith("~") else fpath
        try:
            content = await sandbox.read_file(full)
            file_contents[fpath] = content[:4000]  # cap per-file
        except Exception:
            pass

    return file_contents


def _tail(text: str, n: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:]) if len(lines) >= n else text
