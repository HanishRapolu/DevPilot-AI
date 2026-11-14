import difflib
import io
import json
from pathlib import Path
import subprocess
import tarfile

import httpx
import pytest

from app.config import Settings
from app.mcp_tools.common import ToolError, guarded
from app.mcp_tools.github import GitHubTools
from app.mcp_tools.repository import RepositoryTools
from app.mcp_tools.testing import TestingTools as DockerTestingTools
from app.mcp_tools.workspace import MAX_FILE, MAX_PATCH, Workspace, safe_name
from app.services.approvals import ApprovalStore
from app.services.mcp_client import MCPClientService, validate_arguments


@pytest.fixture
def workspace(tmp_path):
    source = Path(__file__).resolve().parents[2] / "demo-repo"
    return Workspace.create(source, tmp_path, "example/demo", ["calculator.py", "test_calculator.py"], demo=True)


def fix_patch(workspace):
    before = workspace.read("calculator.py")
    after = before.replace("len(values) + 1", "len(values)")
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                       fromfile="a/calculator.py", tofile="b/calculator.py"))


def test_valid_access_and_literal_search(workspace):
    tools = RepositoryTools(workspace)
    assert len(tools.list_files()["files"]) == 4
    assert "def average" in tools.read_file("calculator.py")["content"]
    assert tools.search_code("def average")["matches"][0]["path"] == "calculator.py"
    assert tools.search_code(".*")["matches"] == []


@pytest.mark.parametrize("path", ["../.env", "/etc/passwd", "C:/Windows/win.ini", "a\\b.py",
    "a/../../x.py", ".env", ".env.example", ".git/config", ".github/workflows/test.yml", ".aws/config",
    "credentials.json", "secret.txt", "id_rsa.txt", "x.py:stream", "NUL.py", "a//b.py", "a/./b.py",
    "node_modules/x.py", "venv/x.py", "a./b.py", "a\x00.py", "script.exe"])
def test_invalid_path_rejection(path):
    with pytest.raises(ToolError):
        safe_name(path)


def test_no_unknown_file_access(workspace):
    (workspace.root / "unknown.py").write_text("print('hidden')")
    with pytest.raises(ToolError):
        RepositoryTools(workspace).read_file("unknown.py")


def test_size_limit(workspace):
    (workspace.root / "calculator.py").write_bytes(b"x" * (MAX_FILE + 1))
    with pytest.raises(ToolError):
        RepositoryTools(workspace).read_file("calculator.py")


def test_symlink_escape(workspace, tmp_path):
    target = tmp_path / "outside.py"
    target.write_text("secret")
    file = workspace.root / "calculator.py"
    file.unlink()
    try:
        file.symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks requires Windows privileges")
    with pytest.raises(ToolError, match="Symlinks"):
        RepositoryTools(workspace).read_file("calculator.py")


def test_hard_link_rejected(workspace, tmp_path):
    target = tmp_path / "outside.py"
    target.write_text("secret")
    file = workspace.root / "calculator.py"
    file.unlink()
    try:
        file.hardlink_to(target)
    except OSError:
        pytest.skip("Hard links unavailable on this filesystem")
    with pytest.raises(ToolError):
        RepositoryTools(workspace).read_file("calculator.py")


def test_patch_and_isolation(workspace):
    tools = RepositoryTools(workspace)
    baseline = (workspace.baseline / "calculator.py").read_bytes()
    result = tools.apply_patch(fix_patch(workspace))
    assert result["changed_files"] == ["calculator.py"]
    assert tools.get_diff()["sha256"] == result["diff_sha256"]
    assert (workspace.baseline / "calculator.py").read_bytes() == baseline
    assert "len(values) + 1" not in workspace.read("calculator.py")


@pytest.mark.parametrize("kind", ["traversal", "protected", "unauthorized", "mismatch", "large", "mode", "create"])
def test_bad_patch_is_nonmutating(workspace, kind):
    patch = fix_patch(workspace)
    original = workspace.read("calculator.py")
    if kind == "traversal": patch = patch.replace("calculator.py", "../calculator.py")
    if kind == "protected": patch = patch.replace("calculator.py", ".env")
    if kind == "unauthorized": patch = patch.replace("calculator.py", "README.md")
    if kind == "mismatch": patch = patch.replace("len(values) + 1", "len(values) + 900")
    if kind == "large": patch = "x" * (MAX_PATCH + 1)
    if kind == "mode": patch = "old mode 100644\nnew mode 100755\n" + patch
    if kind == "create": patch = patch.replace("--- a/calculator.py", "--- /dev/null")
    with pytest.raises(ToolError):
        RepositoryTools(workspace).apply_patch(patch)
    assert workspace.read("calculator.py") == original


def test_approval_is_exact_and_one_use(tmp_path):
    store = ApprovalStore(tmp_path / "approvals")
    plan = {"action": "branch", "name": "devpilot/test", "sha": "a" * 40}
    ready, request = store.request_or_consume(plan)
    assert not ready
    assert not store.request_or_consume(plan)[0]
    store.approve(request)
    assert not store.request_or_consume({**plan, "sha": "b" * 40})[0]
    assert store.request_or_consume(plan)[0]
    with pytest.raises(ToolError, match="consumed"):
        store.request_or_consume(plan)


def test_multifile_patch_validation_is_atomic(workspace):
    original = workspace.read("calculator.py")
    valid = fix_patch(workspace)
    invalid = valid.replace("calculator.py", "../outside.py")
    with pytest.raises(ToolError):
        RepositoryTools(workspace).apply_patch(valid + invalid)
    assert workspace.read("calculator.py") == original


def test_expired_approval_rejected(tmp_path):
    store = ApprovalStore(tmp_path / "approvals")
    _, request = store.request_or_consume({"action": "branch"})
    record = store.load(request)
    record["expires_at"] = 0
    store.save(request, record)
    with pytest.raises(ToolError, match="expired"):
        store.approve(request)


def test_github_issue_read_without_token():
    def handle(request):
        assert request.method == "GET"
        assert request.url.host == "api.github.com"
        assert request.url.path == "/repos/example/demo/issues/7"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"number": 7, "title": "Fix mean", "body": "Incorrect average",
                                        "state": "open", "html_url": "https://github.com/example/demo/issues/7"})
    github = GitHubTools("example/demo", transport=httpx.MockTransport(handle))
    assert github.get_issue("example", "demo", 7)["number"] == 7
    with pytest.raises(ToolError, match="not authorized"):
        github.get_issue("other", "demo", 7)


def test_github_error_sanitized():
    github = GitHubTools("example/demo", transport=httpx.MockTransport(lambda _: httpx.Response(403, json={"message": "secret"})))
    with pytest.raises(ToolError) as exc:
        github.get_repository_info("example", "demo")
    assert "secret" not in str(exc.value)
    assert "403" in str(exc.value)


def test_github_reads_ignore_missing_write_configuration(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/demo")
    monkeypatch.setenv("DEVPILOT_WORKSPACE", "/nonexistent/workspace")
    monkeypatch.setenv("DEVPILOT_APPROVALS", "/nonexistent/approvals")
    github = GitHubTools.from_environment()
    github.transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"full_name": "example/demo"}))
    assert github.get_repository_info("example", "demo")["full_name"] == "example/demo"


def github_fixture(workspace, tmp_path):
    workspace.manifest["revision"] = "a" * 40  # Synthetic metadata: all HTTP remains mocked.
    store = ApprovalStore(tmp_path / "approvals")
    calls = []
    state = {"head": "a" * 40}
    def handle(request):
        payload = json.loads(request.content) if request.content else None
        path = request.url.path
        calls.append((request.method, path, payload))
        if request.method == "GET" and "git/ref/heads/" in path:
            return httpx.Response(200, json={"object": {"sha": state["head"] if "devpilot" in path else "a" * 40}})
        if request.method == "GET" and "git/commits/" in path:
            return httpx.Response(200, json={"tree": {"sha": "b" * 40}})
        if path.endswith("git/trees"):
            return httpx.Response(201, json={"sha": "c" * 40})
        if path.endswith("git/commits"):
            return httpx.Response(201, json={"sha": "d" * 40})
        if request.method == "PATCH":
            state["head"] = payload["sha"]
            return httpx.Response(200, json={})
        if path.endswith("pulls"):
            return httpx.Response(201, json={"number": 9, "html_url": "https://github.com/example/demo/pull/9"})
        return httpx.Response(201, json={})
    return GitHubTools("example/demo", "test-only", workspace, store, httpx.MockTransport(handle)), store, calls


def test_branch_requires_backend_approval(workspace, tmp_path):
    github, store, calls = github_fixture(workspace, tmp_path)
    pending = github.create_branch("devpilot/fix", "main")
    assert pending["status"] == "approval_required"
    assert all(method == "GET" for method, _, _ in calls)
    store.approve(pending["request_id"])
    assert github.create_branch("devpilot/fix", "main")["status"] == "created"
    assert calls[-1][2]["ref"] == "refs/heads/devpilot/fix"


def test_pr_publishes_exact_commit_before_draft(workspace, tmp_path):
    github, store, calls = github_fixture(workspace, tmp_path)
    RepositoryTools(workspace).apply_patch(fix_patch(workspace))
    pending = github.create_draft_pr("devpilot/fix", "main", "Fix average")
    assert pending["status"] == "approval_required"
    assert all(method == "GET" for method, _, _ in calls)
    store.approve(pending["request_id"])
    result = github.create_draft_pr("devpilot/fix", "main", "Fix average")
    assert result["commit_sha"] == "d" * 40
    writes = [(method, path, payload) for method, path, payload in calls if method != "GET"]
    assert [method for method, _, _ in writes] == ["POST", "POST", "PATCH", "POST"]
    assert writes[0][2]["tree"][0]["content"] == workspace.read("calculator.py")
    assert writes[2][2] == {"sha": "d" * 40, "force": False}
    assert writes[-1][2]["draft"] is True


def test_patch_change_invalidates_approval(workspace, tmp_path):
    github, store, calls = github_fixture(workspace, tmp_path)
    RepositoryTools(workspace).apply_patch(fix_patch(workspace))
    pending = github.create_draft_pr("devpilot/fix", "main", "Fix average")
    store.approve(pending["request_id"])
    path = workspace.root / "calculator.py"
    path.write_text(workspace.read("calculator.py") + "\n# Another change\n", encoding="utf-8")
    changed = github.create_draft_pr("devpilot/fix", "main", "Fix average")
    assert changed["status"] == "approval_required"
    assert changed["request_id"] != pending["request_id"]
    assert all(method == "GET" for method, _, _ in calls)


def test_demo_cannot_publish(workspace, tmp_path):
    github = GitHubTools("example/demo", "test-only", workspace, ApprovalStore(tmp_path / "approvals"))
    with pytest.raises(ToolError, match="real authorized"):
        github.create_branch("devpilot/test")


def test_docker_command_and_results(workspace):
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        if command[1] == "rm":
            return subprocess.CompletedProcess(command, 0, b"", b"")
        assert "--network=none" in command and "--user=65534:65534" in command
        assert "--read-only" in command and "--cap-drop=ALL" in command
        assert "--memory=256m" in command and "--pull=never" in command
        assert not any("mount" in arg or "docker.sock" in arg for arg in command)
        with tarfile.open(fileobj=io.BytesIO(kwargs["input"]), mode="r:") as archive:
            assert set(archive.getnames()) == set(workspace.files)
            assert all(member.isfile() for member in archive.getmembers())
        return subprocess.CompletedProcess(command, 1, b'{"status":"failed","output":"2 failed, 2 passed"}', b"")
    tools = DockerTestingTools(workspace, runner=runner)
    assert tools.get_test_results()["status"] == "not_run"
    result = tools.run_tests()
    assert result["exit_code"] == 1 and result["status"] == "failed"
    assert result["duration_seconds"] >= 0 and result["cleanup_confirmed"]
    assert tools.get_test_results() == result
    assert calls[-1][:3] == ["docker", "rm", "-f"]


def test_docker_timeout_removes_container(workspace):
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, 1)
        return subprocess.CompletedProcess(command, 0, b"", b"")
    result = DockerTestingTools(workspace, runner=runner).check_syntax()
    assert result["status"] == "timeout"
    assert calls[-1][1:3] == ["rm", "-f"]


def test_client_rejects_extra_approval_and_invalid_arguments():
    schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    assert validate_arguments(schema, {"path": "calculator.py"})
    assert not validate_arguments(schema, {"path": "calculator.py", "approved": True})
    assert not validate_arguments(schema, {"path": 3})


def test_child_environment_has_no_unrelated_secrets(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-leak")
    monkeypatch.setenv("MONGODB_URI", "must-not-leak")
    service = MCPClientService(Settings(_env_file=None, github_token="github-test-only"))
    for name in ("repository", "testing", "github"):
        env = service.environment(name)
        assert "OPENROUTER_API_KEY" not in env and "MONGODB_URI" not in env
        assert ("GITHUB_TOKEN" in env) == (name == "github")


def test_structured_error_does_not_leak_details():
    @guarded
    def bad():
        raise RuntimeError("secret credential")
    assert bad()["ok"] is False
    assert "secret" not in json.dumps(bad())
