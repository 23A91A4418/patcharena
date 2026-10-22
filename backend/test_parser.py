"""JUnit XML parser for test name comparison between baseline and final runs."""

from __future__ import annotations
import re


def parse_test_names_from_output(output: str) -> tuple[set[str], set[str]]:
    """
    Parse pytest -rA or --tb=short output to extract passing and failing test names.
    Returns (passing_names, failing_names).
    """
    passing: set[str] = set()
    failing: set[str] = set()

    # Match lines like: PASSED tests/test_foo.py::test_bar
    for m in re.finditer(r"^(PASSED|FAILED|ERROR)\s+([\w/.\-:]+)", output, re.MULTILINE):
        status, name = m.group(1), m.group(2).strip()
        if status == "PASSED":
            passing.add(name)
        else:
            failing.add(name)

    # Also match short format: tests/test_foo.py::test_bar PASSED
    for m in re.finditer(r"^([\w/.\-:]+)\s+(PASSED|FAILED|ERROR)", output, re.MULTILINE):
        name, status = m.group(1).strip(), m.group(2)
        if status == "PASSED":
            passing.add(name)
        else:
            failing.add(name)

    return passing, failing


def parse_junit_xml(xml_text: str) -> tuple[set[str], set[str]]:
    """
    Parse JUnit XML to extract (passing_names, failing_names).
    Handles pytest's --junitxml output format.
    """
    passing: set[str] = set()
    failing: set[str] = set()

    # <testcase classname="tests.test_foo" name="test_bar" ...>
    #   <failure .../>   ← means it failed
    # </testcase>
    testcase_pattern = re.compile(
        r'<testcase\s+[^>]*classname="([^"]*)"[^>]*name="([^"]*)"[^>]*/?>',
        re.DOTALL,
    )
    failure_pattern = re.compile(r'<(failure|error)\b')

    # Split into testcase blocks to check for nested failure tags
    blocks = re.split(r'(?=<testcase\s)', xml_text)
    for block in blocks:
        m = testcase_pattern.search(block)
        if not m:
            continue
        classname, testname = m.group(1), m.group(2)
        full_name = f"{classname}::{testname}".replace(".", "/", 1) if "." in classname else f"{classname}::{testname}"
        if failure_pattern.search(block):
            failing.add(full_name)
        else:
            passing.add(full_name)

    return passing, failing


def compare_test_results(
    baseline_output: str,
    final_output: str,
    baseline_xml: str = "",
    final_xml: str = "",
) -> tuple[bool, bool, list[str]]:
    """
    Compare baseline vs final test outcomes.

    Returns:
        at_least_one_new_pass: bool  — at least one test went FAIL→PASS
        no_regression:         bool  — no test went PASS→FAIL
        details:               list of human-readable strings
    """
    # Prefer XML if available, fall back to stdout parsing
    if baseline_xml and final_xml:
        base_pass, base_fail = parse_junit_xml(baseline_xml)
        final_pass, final_fail = parse_junit_xml(final_xml)
    else:
        base_pass, base_fail = parse_test_names_from_output(baseline_output)
        final_pass, final_fail = parse_test_names_from_output(final_output)

    newly_passing = base_fail & final_pass      # was failing, now passing ✅
    regressions = base_pass & final_fail        # was passing, now failing ❌

    at_least_one_new_pass = len(newly_passing) > 0
    no_regression = len(regressions) == 0

    details = []
    if newly_passing:
        details.append(f"✅ Newly fixed: {', '.join(sorted(newly_passing)[:5])}")
    else:
        details.append("⚠️ No previously-failing tests were newly fixed")
    if regressions:
        details.append(f"❌ Regressions: {', '.join(sorted(regressions)[:5])}")

    return at_least_one_new_pass, no_regression, details
