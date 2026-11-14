"""Single-process worker; no distributed queue or automatic write retries."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from app.mcp_tools.workspace import Workspace
from app.workflow.runtime import Runtime


class Jobs:
    def __init__(self, settings, db):
        self.settings, self.db = settings, db
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="devpilot")

    def submit(self, task_id, approved=None, expected=None):
        self.pool.submit(self.execute, task_id, approved, expected)

    def execute(self, task_id, approved, expected):
        runtime = None
        try:
            binding = self.db.workflow_workspaces.find_one({"task_id": task_id})
            if binding:
                directory = Path(binding["_id"])
            else:
                if not self.settings.repository_source:
                    raise ValueError("Repository source not configured")
                directory = Workspace.create(self.settings.repository_source, self.settings.mcp_state_dir,
                    self.settings.github_repository, self.settings.repository_allowed_files).directory
            runtime = Runtime(self.settings.model_copy(update={"mcp_workspace": directory}))
            runtime.run(task_id, approved, expected)
        except Exception as exc:
            self.db.tasks.update_one({"_id": task_id}, {"$set": {"status": "failed", "approval": None,
                "workflow.error": f"Execution stopped ({type(exc).__name__}). Check local services/configuration. Inspect GitHub before retrying publication.",
                "updated_at": datetime.now(timezone.utc)},
                "$push": {"status_history": {"status": "failed", "timestamp": datetime.now(timezone.utc)}}})
        finally:
            if runtime:
                runtime.close()

    def close(self):
        self.pool.shutdown(wait=True)
