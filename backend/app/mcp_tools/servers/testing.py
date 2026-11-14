from mcp.server.fastmcp import FastMCP

from app.mcp_tools.common import guarded
from app.mcp_tools.testing import TestingTools

mcp = FastMCP("DevPilot Testing")


@mcp.tool()
@guarded
def run_tests() -> dict:
    """Run fixed Python/Pytest command in a network-disabled, resource-limited Docker container."""
    return TestingTools.from_environment().run_tests()


@mcp.tool()
@guarded
def get_test_results() -> dict:
    """Return the last run's status, exit code, duration, snapshot digest, and bounded output."""
    return TestingTools.from_environment().get_test_results()


@mcp.tool()
@guarded
def check_syntax() -> dict:
    """Parse Python files inside the same restricted Docker sandbox."""
    return TestingTools.from_environment().check_syntax()


if __name__ == "__main__":
    mcp.run(transport="stdio")
