"""Human-only approval UI. Never expose this command as an agent or MCP tool."""
import argparse
import json
import sys

from app.config import Settings
from app.mcp_tools.common import ToolError
from app.services.approvals import ApprovalStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_id")
    args = parser.parse_args()
    store = ApprovalStore(Settings().mcp_state_dir.resolve() / "approvals")
    record = store.load(args.request_id)
    # JSON encoding escapes terminal control characters in untrusted titles/body/patches.
    print(json.dumps(record, indent=2, ensure_ascii=True))
    if not sys.stdin.isatty():
        raise ToolError("Approval requires an interactive human terminal.")
    expected = "APPROVE " + args.request_id
    if input("Review the exact repository, refs, PR text, and patch above. Type '" + expected + "': ").strip() != expected:
        raise ToolError("Approval cancelled.")
    store.approve(args.request_id)
    print("Approved once. Retry the original MCP write call with unchanged arguments.")


if __name__ == "__main__":
    try:
        main()
    except ToolError as exc:
        raise SystemExit(str(exc))
