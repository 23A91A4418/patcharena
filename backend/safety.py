"""Pre-execution command safety hook for PatchArena.

This module provides application-level command validation (defence in depth).
Every command that passes through Sandbox.run() is checked here BEFORE it
reaches the Celesto execution layer.

IMPORTANT LIMITATION: This is application-level filtering, not an
OS/hypervisor security boundary. It is defence-in-depth alongside VM
isolation. A determined attacker with shell access to the guest could bypass
this layer directly. Never claim this is equivalent to kernel-enforced isolation.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Audit log — append-only, never contains secrets
# ---------------------------------------------------------------------------

_AUDIT_LOG_PATH = os.environ.get("COMMAND_AUDIT_LOG", "logs/commands.jsonl")
_AUDIT_LOCK = None  # created on first use (asyncio.Lock is not module-level safe)


def _append_audit(
    sandbox_name: str,
    command_summary: str,
    decision: str,
    reason: str,
    run_id: str = "",
    candidate_id: str = "",
) -> None:
    """Append one structured line to the audit log. Never writes secrets."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sandbox_name": sandbox_name,
        "command": command_summary,
        "decision": decision,
        "reason": reason,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "execution_target": "celesto_sandbox",
    }
    try:
        os.makedirs(os.path.dirname(_AUDIT_LOG_PATH) or ".", exist_ok=True)
        with open(_AUDIT_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass  # never let audit failure break execution


# ---------------------------------------------------------------------------
# Block / allow decision
# ---------------------------------------------------------------------------

class SafetyDecision(NamedTuple):
    allowed: bool
    reason: str


# Patterns that are always blocked regardless of context.
# These catch high-risk operations that the agent should never need.
_BLOCK_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Reading/exfiltrating secrets and system credentials
    (re.compile(r"\bcat\b.*/etc/(passwd|shadow|sudoers)", re.I),
     "reading host credential files"),
    (re.compile(r"\bcat\b.*\.\benv\b", re.I),
     "reading .env files"),
    # Outbound exfiltration to external URLs (catches prompt injection payloads)
    (re.compile(
        r"\bcurl\b[^|;]*https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)",
        re.I),
     "outbound curl to external host — likely exfiltration attempt"),
    (re.compile(
        r"\bwget\b[^|;]*https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)",
        re.I),
     "outbound wget to external host"),
    # Environment variable exfiltration
    (re.compile(r"\$\{?(?:CELESTO|LLM|GITHUB|AWS|GCP|AZURE)_[A-Z_]*KEY\b", re.I),
     "referencing a secret environment variable"),
    # Dangerous destructive operations outside the work dir
    (re.compile(r"\brm\s+-[rf]*\s+/(?!tmp|home/\w+/work)", re.I),
     "potentially destructive rm outside work directories"),
    # Host mount traversal
    (re.compile(r"\.\./\.\./\.\.", re.I),
     "deep relative path traversal"),
    # Fork bomb pattern
    (re.compile(r":\(\)\{.*\|.*:\&", re.I),
     "fork bomb pattern"),
    # Writing to /etc or /usr system directories
    (re.compile(r"\b(echo|tee|cp|mv)\b[^>]*>\s*/(?:etc|usr|bin|sbin)/", re.I),
     "writing to system directory"),
]

# Commands that are safe by construction (application-owned infrastructure commands).
# These skip pattern checking because they are hardcoded by the application, not LLM-generated.
_TRUSTED_PREFIXES: tuple[str, ...] = (
    "git clone ",
    "git checkout ",
    "git diff",
    "git log",
    "pip install ",
    "python -m pytest",
    "mkdir -p ",
    "cat ",
    "find ",
    "cd ",
    "python app.py",
    "nohup ",
    "curl -sf http://localhost",  # health check inside sandbox
)


def validate_command(
    command: str,
    *,
    sandbox_name: str,
    run_id: str = "",
    candidate_id: str = "",
    trusted: bool = False,
) -> SafetyDecision:
    """
    Evaluate a command before it reaches Celesto.

    Parameters
    ----------
    command:       The full shell command string.
    sandbox_name:  The Celesto computer ID/name this will run on.
    run_id:        Arena run identifier (for the audit log).
    candidate_id:  Strategy identifier (for the audit log).
    trusted:       If True, skip pattern checks (use only for application-
                   owned commands, never for LLM-generated content).

    Returns
    -------
    SafetyDecision(allowed=True/False, reason=str)
    """
    # Truncate for the audit log — never log the full command if it may
    # contain interpolated secrets. We log a safe summary instead.
    summary = _safe_summary(command)

    if trusted:
        _append_audit(sandbox_name, summary, "allow", "trusted-app-command",
                      run_id, candidate_id)
        return SafetyDecision(allowed=True, reason="trusted-app-command")

    # Check block patterns
    for pattern, description in _BLOCK_PATTERNS:
        if pattern.search(command):
            _append_audit(sandbox_name, summary, "block", description,
                          run_id, candidate_id)
            return SafetyDecision(allowed=False, reason=description)

    _append_audit(sandbox_name, summary, "allow", "passed-all-checks",
                  run_id, candidate_id)
    return SafetyDecision(allowed=True, reason="passed-all-checks")


def _safe_summary(command: str) -> str:
    """
    Return a short, secret-free summary of a command for the audit log.
    Strips anything that looks like a Base64 blob, a token, or a key value.
    """
    # Remove long base64-like strings
    cleaned = re.sub(r"[A-Za-z0-9+/]{40,}={0,2}", "<b64-blob>", command)
    # Remove anything after a = that looks like a key/secret
    cleaned = re.sub(r"(_KEY|_TOKEN|_SECRET|_PASSWORD)=[^\s;|&]+", r"\1=<redacted>", cleaned, flags=re.I)
    return cleaned[:300]
