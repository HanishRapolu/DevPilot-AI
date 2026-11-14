"""Human-operated workflow runner; not an MCP tool or unauthenticated HTTP endpoint."""
import argparse
import json
import sys
from app.workflow.runtime import Runtime
from app.services.approvals import ApprovalStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--decide", action="store_true")
    args = parser.parse_args()
    runtime = Runtime()
    try:
        result = runtime.run(args.task_id)
        print(json.dumps(result, indent=2, ensure_ascii=True, default=str))
        if args.decide:
            if not result["interrupts"] or not sys.stdin.isatty():
                raise ValueError("An interactive terminal and pending interrupt are required")
            payload = result["interrupts"][0]
            if payload["kind"] == "github_write":
                print(json.dumps(ApprovalStore(runtime.settings.mcp_state_dir / "approvals").load(payload["request_id"]), indent=2, ensure_ascii=True))
            answer = input("Review the exact request above. Type APPROVE or REJECT: ")
            if answer not in ("APPROVE", "REJECT"):
                raise ValueError("Decision cancelled")
            print(json.dumps(runtime.run(args.task_id, approved=answer == "APPROVE"), indent=2, ensure_ascii=True, default=str))
    finally:
        runtime.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "message": "Workflow failed; check local configuration. Raw errors suppressed to protect credentials."}))
        raise SystemExit(1)
