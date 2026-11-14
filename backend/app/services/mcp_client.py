"""The only agent-facing gateway to GitHub, repository, and testing operations."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
from typing import Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

from app.config import Settings

ServerName = Literal["github", "repository", "testing"]
MODULES = {name: f"app.mcp_tools.servers.{name}" for name in ("github", "repository", "testing")}
BACKEND = Path(__file__).resolve().parents[2]


class MCPResult(BaseModel):
    ok: bool
    server: str
    tool: str | None = None
    data: dict = Field(default_factory=dict)
    error: dict | None = None


def validate_arguments(schema: dict, arguments: dict) -> bool:
    # FastMCP's Pydantic defaults may ignore unknown fields; the gateway never does.
    strict = {**schema, "additionalProperties": False}
    try:
        if not isinstance(arguments, dict) or len(json.dumps(arguments).encode()) > 128 * 1024:
            return False
        return not list(Draft202012Validator(strict).iter_errors(arguments))
    except (TypeError, ValueError):
        return False


class MCPClientService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def environment(self, server: str) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC"}}
        env.update(PYTHONPATH=str(BACKEND), PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        if self.settings.mcp_workspace:
            env["DEVPILOT_WORKSPACE"] = str(self.settings.mcp_workspace.resolve())
        if server == "github":
            env.update(GITHUB_REPOSITORY=self.settings.github_repository,
                       GITHUB_TOKEN=self.settings.github_token.get_secret_value(),
                       DEVPILOT_APPROVALS=str(self.settings.mcp_state_dir.resolve() / "approvals"))
        if server == "testing":
            env.update(SANDBOX_IMAGE=self.settings.sandbox_image,
                       SANDBOX_TIMEOUT_SECONDS=str(self.settings.sandbox_timeout_seconds))
        return env

    async def discover(self, server: ServerName) -> MCPResult:
        return await self._request(server)

    async def discover_all(self) -> dict[str, MCPResult]:
        # Sequential startup keeps diagnostics straightforward for this local MVP.
        return {name: await self.discover(name) for name in MODULES}

    async def call(self, server: ServerName, tool: str, arguments: dict | None = None) -> MCPResult:
        return await self._request(server, tool, arguments or {})

    async def _request(self, server: str, tool: str | None = None, arguments: dict | None = None) -> MCPResult:
        def failed(code, message):
            return MCPResult(ok=False, server=server, tool=tool, error={"code": code, "message": message})
        if server not in MODULES:
            return failed("unknown_server", "Server is not registered.")
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            return failed("missing_dependency", "Install backend requirements including the official mcp SDK.")
        params = StdioServerParameters(command=sys.executable, args=["-m", MODULES[server]],
                                       cwd=str(BACKEND), env=self.environment(server))
        try:
            # A connection per operation avoids persistent task-group lifecycle complexity.
            async with asyncio.timeout(self.settings.mcp_timeout_seconds):
                # Server logs never become tool output. Protocol traffic alone uses stdout.
                with open(os.devnull, "w") as errlog:
                    async with stdio_client(params, errlog=errlog) as (read, write):
                        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=self.settings.mcp_timeout_seconds)) as session:
                            await session.initialize()
                            discovered = await session.list_tools()
                            tools = {entry.name: entry for entry in discovered.tools}
                            if tool is None:
                                return MCPResult(ok=True, server=server, data={"tools": [
                                    {"name": entry.name, "description": entry.description, "input_schema": entry.inputSchema}
                                    for entry in tools.values()]})
                            if tool not in tools:
                                return failed("unknown_tool", "Tool was not advertised by this server.")
                            if not validate_arguments(tools[tool].inputSchema, arguments):
                                return failed("invalid_arguments", "Arguments do not match the discovered tool schema.")
                            response = await session.call_tool(tool, arguments=arguments)
                            if response.isError:
                                return failed("mcp_tool_error", "The MCP server rejected the tool call.")
                            payload = response.structuredContent
                            if payload is None:
                                payload = json.loads(next(block.text for block in response.content if block.type == "text"))
                            if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
                                return failed("invalid_result", "MCP server returned an invalid result envelope.")
                            return MCPResult(ok=payload["ok"], server=server, tool=tool,
                                             data=payload.get("data", {}), error=payload.get("error"))
        except TimeoutError:
            return failed("timeout", "MCP connection or tool call exceeded its deadline; inspect write approval state before retrying writes.")
        except Exception:
            return failed("connection_failed", "MCP server failed to connect or returned an invalid response.")
