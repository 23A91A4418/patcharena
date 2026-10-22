"""Configuration and environment loading."""

import os
from dotenv import load_dotenv

load_dotenv()

CELESTO_API_KEY: str = os.environ.get("CELESTO_API_KEY", "")
LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "gemini")
LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "")
LLM_MODEL: str = os.environ.get("LLM_MODEL", "gemini-2.0-flash")
GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")
DEMO_REPO: str = os.environ.get("DEMO_REPO", "")
MAX_PARALLEL: int = int(os.environ.get("MAX_PARALLEL", "3"))
SANDBOX_TIMEOUT_S: int = int(os.environ.get("SANDBOX_TIMEOUT_S", "420"))
MAX_AGENT_STEPS: int = int(os.environ.get("MAX_AGENT_STEPS", "4"))
REPLAY_MODE: bool = os.environ.get("REPLAY_MODE", "false").lower() == "true"

# Sandbox naming
SANDBOX_PREFIX = "pa"

# Safety: paths forbidden from editing
FORBIDDEN_PATH_PATTERNS = [
    ".github/",
    ".env",
    "*.pem",
    "*.key",
    "package-lock.json",
    "poetry.lock",
    "Pipfile.lock",
    "..",
]

# Redaction patterns for logs
REDACT_KEYS = [
    CELESTO_API_KEY,
    LLM_API_KEY,
    GITHUB_TOKEN,
]


def redact(text: str) -> str:
    """Redact sensitive keys from log output."""
    result = text
    for key in REDACT_KEYS:
        if key and len(key) > 4:
            result = result.replace(key, f"{key[:4]}***REDACTED***")
    return result
