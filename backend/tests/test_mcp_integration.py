"""Actual MCP initialize/list_tools/call_tool over subprocess stdio, not function mocks."""
import asyncio
import os
from pathlib import Path
import sys

import pytest

pytest.importorskip("mcp", reason="Official MCP SDK is not installed; protocol tests cannot run")

from app.config import Settings
from app.mcp_tools.workspace import Workspace
from app.services.mcp_client import MCPClientService, MODULES

pytestmark = pytest.mark.mcp


@pytest.fixture
def client(tmp_path):
    fixture = Path(__file__).resolve().parents[2] / "demo-repo"
    workspace = Workspace.create(fixture, tmp_path, "example/demo", ["calculator.py", "test_calculator.py"], demo=True)
    return MCPClientService(Settings(_env_file=None, github_repository="example/demo", github_token="",
                                     mcp_workspace=workspace.directory, mcp_state_dir=tmp_path,
                                     mcp_timeout_seconds=15, sandbox_image="devpilot-python-tests:phase2"))


def test_all_server_discovery(client):
    async def check():
        discovered = await client.discover_all()
        expected = {"github": {"get_issue", "get_repository_info", "create_branch", "create_draft_pr"},
                    "repository": {"list_files", "read_file", "search_code", "apply_patch", "get_diff"},
                    "testing": {"run_tests", "get_test_results", "check_syntax"}}
        for server, names in expected.items():
            assert discovered[server].ok, discovered[server].error
            assert {entry["name"] for entry in discovered[server].data["tools"]} == names
    asyncio.run(check())


def test_repository_invocation_and_errors(client):
    async def check():
        good = await client.call("repository", "read_file", {"path": "calculator.py"})
        assert good.ok and "def average" in good.data["content"]
        rejected = await client.call("repository", "read_file", {"path": "../.env"})
        assert not rejected.ok and rejected.error["code"] == "rejected"
        extra = await client.call("repository", "read_file", {"path": "calculator.py", "approved": True})
        assert not extra.ok and extra.error["code"] == "invalid_arguments"
        unknown = await client.call("repository", "execute_shell", {"command": "whoami"})
        assert not unknown.ok and unknown.error["code"] == "unknown_tool"
        cached = await client.call("testing", "get_test_results")
        assert cached.ok and cached.data["status"] == "not_run"
    asyncio.run(check())


def test_protocol_patch_roundtrip(client):
    import difflib
    async def check():
        before = await client.call("repository", "read_file", {"path": "calculator.py"})
        original = before.data["content"]
        updated = original.replace("len(values) + 1", "len(values)")
        patch = "".join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True), fromfile="a/calculator.py", tofile="b/calculator.py"))
        applied = await client.call("repository", "apply_patch", {"patch": patch})
        assert applied.ok, applied.error
        diff = await client.call("repository", "get_diff")
        assert diff.ok and diff.data["sha256"] == applied.data["diff_sha256"]
    asyncio.run(check())


def test_connection_failure_is_structured(client, monkeypatch):
    monkeypatch.setitem(MODULES, "repository", "module_that_does_not_exist")
    response = asyncio.run(client.discover("repository"))
    assert not response.ok and response.error["code"] in ("connection_failed", "timeout")


def test_timeout_is_structured(client, monkeypatch):
    # Real subprocess that speaks no MCP; no shell command and no network.
    from mcp.client import stdio
    import mcp
    original = mcp.StdioServerParameters
    def parameters(**kwargs):
        kwargs["args"] = ["-c", "import time; time.sleep(30)"]
        return original(**kwargs)
    monkeypatch.setattr(mcp, "StdioServerParameters", parameters)
    client.settings.mcp_timeout_seconds = 0.2
    response = asyncio.run(client.discover("repository"))
    assert not response.ok and response.error["code"] in ("timeout", "connection_failed")


@pytest.mark.docker
@pytest.mark.skipif(os.environ.get("DEVPILOT_RUN_DOCKER_TESTS") != "1", reason="Set DEVPILOT_RUN_DOCKER_TESTS=1 after building the sandbox image")
def test_actual_docker_via_mcp(client):
    client.settings.mcp_timeout_seconds = 150
    async def check():
        syntax = await client.call("testing", "check_syntax")
        assert syntax.ok and syntax.data["status"] == "passed", syntax.model_dump()
        tests = await client.call("testing", "run_tests")
        assert tests.ok and tests.data["exit_code"] == 1, tests.model_dump()
        assert "2 failed, 2 passed" in tests.data["output"]
    asyncio.run(check())
