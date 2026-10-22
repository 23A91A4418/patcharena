"""Strategy definitions for PatchArena."""

from .models import Strategy

STRATEGY_REGISTRY: dict[str, Strategy] = {
    "minimal": Strategy(
        id="minimal",
        name="Minimal Patch",
        description="Smallest possible change at the point of failure.",
        instructions=(
            "Make the smallest possible change to fix the bug. "
            "Touch as few lines as possible. "
            "Do NOT refactor, add abstractions, or change unrelated code. "
            "Prefer one-line fixes when feasible."
        ),
    ),
    "rootcause": Strategy(
        id="rootcause",
        name="Root-Cause Fix",
        description="Fix the underlying cause, even if it touches more than one file.",
        instructions=(
            "Find the underlying root cause of the issue, not just a symptom. "
            "Fix it where it originates, even if that means touching more than one file. "
            "Prefer correctness over minimalism. "
            "Add a brief code comment explaining why the fix addresses the root cause."
        ),
    ),
    "testfirst": Strategy(
        id="testfirst",
        name="Test-First",
        description="Add a failing regression test first, then fix to make it pass.",
        instructions=(
            "First, add a regression test that reproduces the issue and currently fails. "
            "Then fix the code until the new test passes. "
            "The test should be in the existing test file for the affected module. "
            "Your first edit must be the test addition. "
            "Mark the test with a comment: # regression: <issue title>"
        ),
    ),
    "defensive": Strategy(
        id="defensive",
        name="Defensive Validation",
        description="Fix the bug and add input validation so related bugs cannot recur.",
        instructions=(
            "Fix the bug, then add input validation or guard clauses so that "
            "similar bugs cannot recur. "
            "Raise meaningful exceptions with descriptive messages. "
            "Add a docstring or comment explaining the invariant being enforced."
        ),
    ),
}


def get_strategy(strategy_id: str) -> Strategy:
    if strategy_id not in STRATEGY_REGISTRY:
        raise KeyError(f"Unknown strategy: {strategy_id}. Available: {list(STRATEGY_REGISTRY)}")
    return STRATEGY_REGISTRY[strategy_id]


def list_strategies() -> list[Strategy]:
    return list(STRATEGY_REGISTRY.values())
