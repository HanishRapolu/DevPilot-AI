"""Credential-free end-to-end MCP demonstration using real stdio subprocesses."""
import asyncio
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

from app.config import Settings
from app.mcp_tools.workspace import Workspace
from app.services.mcp_client import MCPClientService


async def demonstrate():
    with tempfile.TemporaryDirectory(prefix="devpilot-mcp-") as temporary:
        state = Path(temporary)
        source = Path(__file__).resolve().parents[2] / "demo-repo"
        workspace = Workspace.create(source, state, "example/demo", ["calculator.py", "test_calculator.py"], demo=True)
        settings = Settings(_env_file=None, github_token="", github_repository="example/demo",
                            mcp_workspace=workspace.directory, mcp_state_dir=state, mcp_timeout_seconds=15)
        client = MCPClientService(settings)
        all_tools = await client.discover_all()
        for name, discovered in all_tools.items():
            print(json.dumps({"discovery": name, **discovered.model_dump()}), flush=True)
        for tool, arguments in [("list_files", {}), ("read_file", {"path": "calculator.py"}),
                                ("read_file", {"path": "../.env"})]:
            print((await client.call("repository", tool, arguments)).model_dump_json(), flush=True)
        return 0 if all(item.ok for item in all_tools.values()) else 1


if __name__ == "__main__":
    if importlib.util.find_spec("mcp") is None:
        print('{"ok":false,"error":"missing_dependency","message":"Install backend requirements including mcp before running the stdio demo."}')
        raise SystemExit(1)
    if "--worker" in sys.argv:
        raise SystemExit(asyncio.run(demonstrate()))
    try:
        result = subprocess.run([sys.executable, "-m", "scripts.mcp_demo", "--worker"], timeout=110)
        raise SystemExit(result.returncode)
    except subprocess.TimeoutExpired:
        print('{"ok":false,"error":"Demo timed out; check local asyncio and MCP installation."}')
        raise SystemExit(1)
