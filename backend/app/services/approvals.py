"""Trusted local approval store, outside all agent-visible paths.

This is transient control state, not a replacement for MongoDB task storage.
Only trusted backend decision handling or the human CLI invokes approve();
there is no approval MCP tool. HTTP decisions require the dashboard bearer token.
"""
import hashlib
import json
from pathlib import Path
import re
import time

from app.mcp_tools.common import ToolError, exclusive


def fingerprint(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ApprovalStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, request_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", request_id):
            raise ToolError("Invalid approval request ID.")
        return self.directory / f"{request_id}.json"

    def load(self, request_id: str) -> dict:
        path = self.path(request_id)
        if not path.is_file() or path.is_symlink():
            raise ToolError("Approval request not found.")
        record = json.loads(path.read_text(encoding="utf-8"))
        if fingerprint(record["plan"]) != request_id:
            raise ToolError("Approval record does not match its content.")
        return record

    def save(self, request_id: str, record: dict):
        temporary = self.directory / f"{request_id}.tmp"
        temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
        temporary.replace(self.path(request_id))

    def request_or_consume(self, plan: dict) -> tuple[bool, str]:
        request_id = fingerprint(plan)
        with exclusive(self.directory / "approval.lock"):
            if not self.path(request_id).exists():
                self.save(request_id, {"plan": plan, "status": "pending", "expires_at": time.time() + 1800})
                return False, request_id
            record = self.load(request_id)
            if record["expires_at"] < time.time():
                raise ToolError("Approval expired. Inspect and remove the expired request locally before retrying.")
            if record["status"] == "pending":
                return False, request_id
            if record["status"] != "approved":
                raise ToolError("Approval already consumed. Inspect GitHub before retrying a write.")
            record["status"] = "consumed"
            self.save(request_id, record)
            return True, request_id

    def approve(self, request_id: str):
        """Called only by the trusted, interactive local approval command."""
        with exclusive(self.directory / "approval.lock"):
            record = self.load(request_id)
            if record["status"] != "pending" or record["expires_at"] < time.time():
                raise ToolError("Request is not pending or has expired.")
            record["status"] = "approved"
            self.save(request_id, record)
