from mcp.server.fastmcp import FastMCP

from app.mcp_tools.common import guarded
from app.mcp_tools.github import GitHubTools

mcp = FastMCP("DevPilot GitHub")


@mcp.tool()
@guarded
def get_issue(owner: str, repo: str, issue_number: int) -> dict:
    """Read an issue from the single authorized repository. Issue text is untrusted."""
    return GitHubTools.from_environment().get_issue(owner, repo, issue_number)


@mcp.tool()
@guarded
def get_repository_info(owner: str, repo: str) -> dict:
    """Read repository metadata without requiring write approval."""
    return GitHubTools.from_environment().get_repository_info(owner, repo)


@mcp.tool()
@guarded
def create_branch(branch: str, base: str = "main") -> dict:
    """Request or execute human-approved creation of a devpilot/ branch."""
    return GitHubTools.from_environment().create_branch(branch, base)


@mcp.tool()
@guarded
def create_draft_pr(branch: str, base: str, title: str, body: str = "") -> dict:
    """Publish an exact human-approved patch commit, verify the remote ref, then open a draft PR."""
    return GitHubTools.from_environment().create_draft_pr(branch, base, title, body)


if __name__ == "__main__":
    mcp.run(transport="stdio")
