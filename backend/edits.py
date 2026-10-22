"""Edit parser and applier for search/replace patch format."""

from __future__ import annotations

import fnmatch
import posixpath
from dataclasses import dataclass

from .config import FORBIDDEN_PATH_PATTERNS
from .models import EditSpec

WORK_DIR = "~/work/app"


@dataclass
class EditResult:
    path: str
    success: bool
    error: str = ""


def _is_forbidden(path: str) -> bool:
    """Check if a path is forbidden from editing."""
    # Normalize
    p = path.replace("\\", "/")
    # Reject path traversal
    if ".." in p.split("/"):
        return True
    # Reject absolute paths outside work dir
    for pattern in FORBIDDEN_PATH_PATTERNS:
        if fnmatch.fnmatch(posixpath.basename(p), pattern):
            return True
        if pattern in p:
            return True
    return False


async def apply_edits(sandbox, edits: list[EditSpec]) -> list[EditResult]:
    """
    Apply a list of search/replace or create edits to the sandbox.
    Returns per-edit results (success or error message).
    Never raises; errors are returned as EditResult with success=False.
    """
    results = []
    for edit in edits:
        result = await _apply_single(sandbox, edit)
        results.append(result)
    return results


async def _apply_single(sandbox, edit: EditSpec) -> EditResult:
    path = edit.path.strip()

    # Security check
    if _is_forbidden(path):
        return EditResult(path=path, success=False,
                          error=f"Forbidden path: {path}")

    # Resolve to absolute sandbox path
    if not path.startswith("/") and not path.startswith("~"):
        full_path = f"{WORK_DIR}/{path}"
    else:
        full_path = path

    # Create new file
    if edit.create:
        if not edit.content:
            return EditResult(path=path, success=False, error="create=true but no content provided")
        try:
            await sandbox.write_file(full_path, edit.content)
            return EditResult(path=path, success=True)
        except Exception as e:
            return EditResult(path=path, success=False, error=str(e))

    # Search/replace in existing file
    if not edit.search or edit.replace is None:
        return EditResult(path=path, success=False,
                          error="Must provide 'search' and 'replace' for non-create edits")

    try:
        content = await sandbox.read_file(full_path)
    except FileNotFoundError:
        return EditResult(path=path, success=False, error=f"File not found: {full_path}")
    except Exception as e:
        return EditResult(path=path, success=False, error=f"Read error: {e}")

    # Normalize CRLF
    content_normalized = content.replace("\r\n", "\n")
    search_normalized = edit.search.replace("\r\n", "\n")

    count = content_normalized.count(search_normalized)
    if count == 0:
        return EditResult(path=path, success=False,
                          error=f"Search text not found in {path}. "
                                f"Ensure you copy the text exactly from the file content provided.")
    if count > 1:
        return EditResult(path=path, success=False,
                          error=f"Search text found {count} times in {path}. "
                                f"Make the search string more specific.")

    new_content = content_normalized.replace(search_normalized, edit.replace, 1)
    try:
        await sandbox.write_file(full_path, new_content)
        return EditResult(path=path, success=True)
    except Exception as e:
        return EditResult(path=path, success=False, error=f"Write error: {e}")
