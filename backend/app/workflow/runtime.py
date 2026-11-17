import asyncio
from datetime import datetime, timezone
import secrets
from uuid import UUID

from langgraph.types import Command
from pymongo import MongoClient

from app.config import Settings
from app.mcp_tools.common import exclusive
from app.services.approvals import ApprovalStore, fingerprint
from app.services.llm import OpenRouterService
from app.services.mcp_client import MCPClientService
from app.workflow.graph import Workflow


class Runtime:
    """Trusted local single-user runner. Never expose decision() as an LLM tool."""
    def __init__(self, settings=None):
        from langgraph.checkpoint.mongodb import MongoDBSaver
        self.settings = settings or Settings()
        self.client = MongoClient(self.settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=5000)
        self.db = self.client[self.settings.mongodb_database]
        self.saver = MongoDBSaver(self.client, db_name=self.settings.mongodb_database,
                                 checkpoint_collection_name="workflow_checkpoints",
                                 writes_collection_name="workflow_checkpoint_writes")
        self.mcp = MCPClientService(self.settings)
        self.graph = Workflow(self.llm, self.tool, self.events, self.authorize).build(self.saver)

    def close(self):
        self.client.close()

    @staticmethod
    def projection(value):
        return {key: value.get(key) for key in (
            "issue_details", "plan", "investigation_summary", "change_summary", "changed_files", "diff",
            "test_results", "review_feedback", "retry_count", "approval_status", "current_step", "task_status", "pr_url", "error")}

    def sync_snapshot(self, task_id, snapshot):
        """Repair the UI projection even when recovery only inspects a paused graph."""
        pending = [item.value for task in snapshot.tasks for item in task.interrupts]
        status = "awaiting_approval" if pending else snapshot.values["task_status"]
        approval = None
        if pending:
            approval = {"payload": pending[0], "hash": fingerprint(pending[0])}
            if pending[0]["kind"] == "github_write":
                approval["plan"] = ApprovalStore(self.settings.mcp_state_dir / "approvals").load(pending[0]["request_id"])["plan"]
        self.persist_status(task_id, status, {"workflow": self.projection(snapshot.values), "approval": approval, "decision_claim": None})
        return {"state": snapshot.values, "interrupts": pending}

    def llm(self, prompt, schema):
        async def invoke():
            service = OpenRouterService(self.settings)
            try:
                return await service.generate(prompt, schema)
            finally:
                await service.close()
        return asyncio.run(invoke())

    def tool(self, server, name, arguments):
        return asyncio.run(self.mcp.call(server, name, arguments))

    def events(self, record):
        self.db.workflow_events.insert_one(record.copy())
        if record["status"] == "started":
            self.db.tasks.update_one({"_id": record["task_id"]}, {"$set": {
                "workflow.current_step": record["agent"], "updated_at": datetime.now(timezone.utc)}})

    def persist_status(self, task_id, status, fields):
        """Keep status history in the same atomic document update as the projection."""
        now = datetime.now(timezone.utc)
        update = {**fields, "status": status, "updated_at": now}
        changed = self.db.tasks.update_one({"_id": task_id, "status": {"$ne": status}}, {
            "$set": update, "$push": {"status_history": {"status": status, "timestamp": now}}})
        if changed.modified_count == 0:
            self.db.tasks.update_one({"_id": task_id}, {"$set": update})

    def authorize(self, state, payload, receipt):
        if not isinstance(receipt, str):
            raise PermissionError("Backend-issued receipt required")
        record = self.db.workflow_decisions.find_one({"_id": receipt, "task_id": state["task_id"], "payload_hash": fingerprint(payload)})
        if not record:
            raise PermissionError("Decision not authorized")
        if record["approved"] and payload["kind"] == "github_write":
            store = ApprovalStore(self.settings.mcp_state_dir / "approvals")
            plan = store.load(payload["request_id"])["plan"]
            if plan["repository"] != state["repository"] or plan["branch"] != state["branch"]:
                raise PermissionError("Write request scope mismatch")
            if plan["action"] == "create_draft_pr" and plan["diff"] != state["diff"]:
                raise PermissionError("Write request patch mismatch")
            store.approve(payload["request_id"])
        return record["approved"]

    @staticmethod
    def config(task_id):
        task_id = str(UUID(task_id))
        return {"configurable": {"thread_id": f"task:{task_id}"}, "recursion_limit": 80}

    def run(self, task_id, approved=None, expected_payload_hash=None):
        config = self.config(task_id)
        root = self.settings.mcp_state_dir
        root.mkdir(parents=True, exist_ok=True)
        # Single workspace MVP: serialize runs and bind it permanently to one task.
        with exclusive(root / "workflow.lock"):
            if not self.settings.mcp_workspace:
                binding = self.db.workflow_workspaces.find_one({"task_id": task_id})
                if not binding:
                    raise ValueError("No workspace binding found for task")
                from pathlib import Path
                self.settings = self.settings.model_copy(update={"mcp_workspace": Path(binding["_id"])})
                self.mcp = MCPClientService(self.settings)
            binding = self.db.workflow_workspaces.find_one({"_id": str(self.settings.mcp_workspace.resolve())})
            if binding and binding["task_id"] != task_id:
                raise ValueError("Prepare a new workspace for each task")
            self.db.workflow_workspaces.update_one({"_id": str(self.settings.mcp_workspace.resolve())}, {"$setOnInsert": {"task_id": task_id}}, upsert=True)
            snapshot = self.graph.get_state(config)
            if not snapshot.values:
                if approved is not None:
                    raise ValueError("Task is not awaiting approval")
                task = self.db.tasks.find_one({"_id": task_id})
                if not task or not task.get("issue_number"):
                    raise ValueError("Create a task with an issue number first")
                repository = task["repository_url"].removeprefix("https://github.com/").lower()
                if repository != self.settings.github_repository.lower():
                    raise PermissionError("Repository is not authorized")
                data = {"task_id": task_id, "repository": repository, "issue_number": task["issue_number"],
                        "retry_count": 0, "approval_status": "pending", "task_status": "running",
                        "branch": "devpilot/" + task_id, "pr_url": None, "error": None}
            else:
                if not snapshot.next:
                    return self.sync_snapshot(task_id, snapshot)
                pending = [item for task in snapshot.tasks for item in task.interrupts]
                if pending:
                    if approved is None:
                        return self.sync_snapshot(task_id, snapshot)
                    if expected_payload_hash is not None and fingerprint(pending[0].value) != expected_payload_hash:
                        raise PermissionError("Approval changed since review")
                    receipt = secrets.token_urlsafe(32)
                    self.db.workflow_decisions.insert_one({"_id": receipt, "task_id": task_id,
                        "payload_hash": fingerprint(pending[0].value), "approved": bool(approved),
                        "created_at": datetime.now(timezone.utc)})
                    data = Command(resume=receipt)
                else:
                    if approved is not None:
                        raise ValueError("Task is not awaiting approval")
                    if any(step in ("create_branch", "create_pr") for step in snapshot.next):
                        raise PermissionError("Interrupted publication requires manual GitHub reconciliation; automatic replay is disabled")
                    data = None
            for value in self.graph.stream(data, config, stream_mode="values"):
                view = self.projection(value)
                self.persist_status(task_id, value.get("task_status", "running"), {"workflow": view})
            snapshot = self.graph.get_state(config)
            return self.sync_snapshot(task_id, snapshot)
