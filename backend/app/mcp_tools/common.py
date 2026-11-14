from contextlib import contextmanager
from pathlib import Path
import functools
import os
import re
from typing import Callable


class ToolError(ValueError):
    """Only fixed, safe messages belong in this exception."""


def result(data: dict) -> dict:
    return {"ok": True, "data": data}


def guarded(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return result(fn(*args, **kwargs))
        except ToolError as exc:
            return {"ok": False, "error": {"code": "rejected", "message": str(exc)}}
        except Exception:
            return {"ok": False, "error": {"code": "operation_failed", "message": "Operation failed; inspect local configuration and service availability."}}
    return wrapped


@contextmanager
def exclusive(path: Path):
    """Cross-process, fail-fast lock. A stale lock requires manual inspection."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ToolError("Workspace busy; retry after the current operation finishes.") from None
    try:
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def repository_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) or any(p in (".", "..") for p in value.split("/")):
        raise ToolError("Configure one GitHub repository as owner/repository.")
    return value.lower()
