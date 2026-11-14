"""Trusted setup CLI, not an MCP tool. Does not clone, execute, or publish repository code."""
import argparse
from pathlib import Path

from app.config import Settings
from app.mcp_tools.common import ToolError
from app.mcp_tools.workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.demo:
        source = Path(__file__).resolve().parents[2] / "demo-repo"
        workspace = Workspace.create(source, settings.mcp_state_dir, "example/demo",
                                     ["calculator.py", "test_calculator.py"], demo=True)
    else:
        if not settings.repository_source:
            raise ToolError("Set REPOSITORY_SOURCE to an existing Git checkout in backend/.env.")
        workspace = Workspace.create(settings.repository_source, settings.mcp_state_dir,
                                     settings.github_repository, settings.repository_allowed_files)
    print("Workspace created. Set this non-secret value in backend/.env:")
    print("MCP_WORKSPACE=" + workspace.directory.as_posix())
    print("Source checkout was not modified. Demo workspaces cannot publish GitHub writes.")


if __name__ == "__main__":
    try:
        main()
    except ToolError as exc:
        raise SystemExit(str(exc))
