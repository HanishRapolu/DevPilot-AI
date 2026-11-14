import os
from pathlib import Path
import re
from urllib.parse import quote

import httpx

from app.mcp_tools.common import ToolError, repository_name
from app.mcp_tools.workspace import Workspace
from app.services.approvals import ApprovalStore


class GitHubTools:
    def __init__(self, repository: str, token: str = "", workspace: Workspace | None = None,
                 approvals: ApprovalStore | None = None, transport=None):
        self.repository = repository_name(repository)
        self.token = token
        self.workspace = workspace
        self.approvals = approvals
        self.transport = transport

    @classmethod
    def from_environment(cls):
        # Deliberately do not load backend/.env inside child servers.
        instance = cls(os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GITHUB_TOKEN", ""))
        # Reads must work even if workspace/approval configuration is absent or invalid.
        instance._workspace_path = os.getenv("DEVPILOT_WORKSPACE")
        instance._approvals_path = os.getenv("DEVPILOT_APPROVALS")
        return instance

    def api(self, method: str, endpoint: str, payload: dict | None = None) -> dict:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            with httpx.Client(base_url="https://api.github.com", headers=headers, timeout=15,
                              follow_redirects=False, trust_env=False, transport=self.transport) as client:
                path = f"/repos/{self.repository}" + (f"/{endpoint}" if endpoint else "")
                response = client.request(method, path, json=payload)
                if response.status_code >= 300:
                    raise ToolError(f"GitHub rejected the request (HTTP {response.status_code}).")
                return response.json()
        except httpx.HTTPError:
            raise ToolError("GitHub connection failed or timed out.") from None

    def authorize_repository(self, owner: str, repo: str):
        if repository_name(f"{owner}/{repo}") != self.repository:
            raise ToolError("Repository is not authorized.")

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        self.authorize_repository(owner, repo)
        if type(issue_number) is not int or issue_number < 1:
            raise ToolError("Issue number must be a positive integer.")
        issue = self.api("GET", f"issues/{issue_number}")
        if "pull_request" in issue:
            raise ToolError("Requested number identifies a pull request, not an issue.")
        return {"number": issue["number"], "title": issue["title"][:500],
                "body": (issue.get("body") or "")[:20000], "state": issue["state"],
                "url": issue["html_url"], "untrusted_content": True}

    def get_repository_info(self, owner: str, repo: str) -> dict:
        self.authorize_repository(owner, repo)
        info = self.api("GET", "")
        return {key: info.get(key) for key in ("full_name", "default_branch", "private", "html_url", "description")}

    @staticmethod
    def branch(value: str, write=False) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,99}", value) or "//" in value or value.endswith("/"):
            raise ToolError("Invalid branch name.")
        if write and not re.fullmatch(r"devpilot/[A-Za-z0-9][A-Za-z0-9_-]{0,70}", value):
            raise ToolError("Writes require a dedicated devpilot/ branch.")
        return value

    def head(self, branch: str) -> str:
        data = self.api("GET", "git/ref/heads/" + quote(self.branch(branch), safe=""))
        return data["object"]["sha"]

    def require_write(self):
        if not self.token:
            raise ToolError("Configure GITHUB_TOKEN locally to enable writes; public reads do not require it.")
        if self.workspace is None and getattr(self, "_workspace_path", None):
            self.workspace = Workspace(Path(self._workspace_path))
        if self.approvals is None and getattr(self, "_approvals_path", None):
            self.approvals = ApprovalStore(Path(self._approvals_path))
        if self.approvals is None or self.workspace is None:
            raise ToolError("Write approval store and workspace are required.")
        if self.workspace.manifest["repository"] != self.repository or not self.workspace.manifest["revision"]:
            raise ToolError("A real authorized Git checkout is required for GitHub writes.")

    def approval(self, plan: dict) -> dict | None:
        approved, request_id = self.approvals.request_or_consume(plan)
        if not approved:
            return {"status": "approval_required", "request_id": request_id,
                    "message": "A human must review and approve this exact request using scripts.approve_write locally, then retry unchanged arguments."}
        return None

    def create_branch(self, branch: str, base: str = "main") -> dict:
        self.require_write()
        branch, base = self.branch(branch, True), self.branch(base)
        if branch == base:
            raise ToolError("Source and target branches must differ.")
        with self.workspace.lock():
            sha = self.head(base)
            if sha != self.workspace.manifest["revision"]:
                raise ToolError("Base branch moved or workspace is stale; prepare a fresh workspace.")
            plan = {"action": "create_branch", "repository": self.repository, "branch": branch, "base": base, "base_sha": sha}
            pending = self.approval(plan)
            if pending:
                return pending
            self.api("POST", "git/refs", {"ref": f"refs/heads/{branch}", "sha": sha})
            return {"status": "created", "branch": branch, "sha": sha}

    def create_draft_pr(self, branch: str, base: str, title: str, body: str = "") -> dict:
        self.require_write()
        branch, base = self.branch(branch, True), self.branch(base)
        if branch == base or not 1 <= len(title.strip()) <= 200 or len(body) > 10000:
            raise ToolError("Invalid PR branches, title, or body.")
        with self.workspace.lock():
            base_sha = self.head(base)
            head_sha = self.head(branch)
            if base_sha != self.workspace.manifest["revision"] or head_sha != base_sha:
                raise ToolError("Branch or base moved; only a fresh branch at the workspace revision is supported.")
            diff = self.workspace.diff()
            changes = self.workspace.changes()
            if not changes:
                raise ToolError("No approved-file changes to publish.")
            plan = {"action": "create_draft_pr", "repository": self.repository, "branch": branch,
                    "base": base, "base_sha": base_sha, "head_sha": head_sha, "title": title,
                    "body": body, "diff": diff, "files": changes}
            pending = self.approval(plan)
            if pending:
                return pending
            # Recheck refs immediately before publication. Non-force update rejects divergent races.
            if self.head(base) != base_sha or self.head(branch) != head_sha:
                raise ToolError("Remote refs changed after approval; write rejected.")
            commit = self.api("GET", f"git/commits/{head_sha}")
            tree = self.api("POST", "git/trees", {"base_tree": commit["tree"]["sha"], "tree": [
                {"path": name, "mode": self.workspace.manifest["modes"][name], "type": "blob", "content": text}
                for name, text in sorted(changes.items())]})
            created = self.api("POST", "git/commits", {"message": title, "tree": tree["sha"], "parents": [head_sha]})
            sha = created["sha"]
            # Git Database API publishes the commit to GitHub without exposing a token to git subprocesses.
            self.api("PATCH", "git/refs/heads/" + quote(branch, safe=""), {"sha": sha, "force": False})
            if self.head(branch) != sha:
                raise ToolError("Published branch could not be verified; no PR was opened.")
            pr = self.api("POST", "pulls", {"head": branch, "base": base, "title": title, "body": body, "draft": True})
            return {"status": "draft_created", "number": pr["number"], "url": pr["html_url"], "commit_sha": sha}
