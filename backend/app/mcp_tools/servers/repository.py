from mcp.server.fastmcp import FastMCP

from app.mcp_tools.common import guarded
from app.mcp_tools.repository import RepositoryTools
from app.mcp_tools.workspace import Workspace

mcp = FastMCP("DevPilot Repository")


def implementation():
    return RepositoryTools(Workspace.from_environment())


@mcp.tool()
@guarded
def list_files() -> dict:
    """List safe files in the isolated authorized checkout."""
    return implementation().list_files()


@mcp.tool()
@guarded
def read_file(path: str) -> dict:
    """Read a bounded UTF-8 file. Protected paths and links are rejected."""
    return implementation().read_file(path)


@mcp.tool()
@guarded
def search_code(query: str) -> dict:
    """Search for literal text; no regex or shell execution."""
    return implementation().search_code(query)


@mcp.tool()
@guarded
def apply_patch(patch: str) -> dict:
    """Apply a bounded unified diff only to explicitly authorized existing files."""
    return implementation().apply_patch(patch)


@mcp.tool()
@guarded
def get_diff() -> dict:
    """Return the current patch and its SHA-256 digest."""
    return implementation().get_diff()


if __name__ == "__main__":
    mcp.run(transport="stdio")
