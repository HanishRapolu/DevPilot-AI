# MCP tools and trust boundaries

These are genuine official SDK FastMCP servers using stdio. Run a server from backend with `python -m app.mcp_tools.servers.repository` (or github/testing). Stdout is JSON-RPC protocol output; do not treat it as an interactive CLI.

| Server | Tools | Restrictions |
|---|---|---|
| GitHub | get_issue(owner, repo, issue_number), get_repository_info(owner, repo), create_branch(branch, base), create_draft_pr(branch, base, title, body) | One configured repository; reads independent of writes; exact human authorization; devpilot/ write branches |
| Repository | list_files(), read_file(path), search_code(query), apply_patch(patch), get_diff() | Committed safe text snapshot; literal search; exact editable allowlist; no file creation/deletion/rename |
| Testing | run_tests(), get_test_results(), check_syntax() | Fixed Python/Pytest commands in local Docker; no arbitrary shell input |

MCPClientService starts a server subprocess, initializes ClientSession, discovers tools, validates arguments against the advertised JSON schema (including rejecting extra properties), calls a tool, parses its structured envelope and closes the connection. Connections are per operation for simplicity; process startup adds latency. Unknown servers/tools, invalid arguments, timeouts and broken connections return structured failures.

Example from backend (after preparing MCP_WORKSPACE):

```python
import asyncio
from app.services.mcp_client import MCPClientService
result = asyncio.run(MCPClientService().call("repository", "read_file", {"path": "calculator.py"}))
print(result.model_dump())
```

Actual protocol discovery/read/patch/error tests run with `python -m pytest tests/test_mcp_integration.py -m "not docker" -q`. This demonstrates MCP transport without a real GitHub write. `scripts.mcp_demo` is an additional local protocol demonstration.

## Files and patches

Reject absolute paths, traversal, hidden files including .env/.git/.github, credential-related names, unsupported extensions, symlinks, junctions, hard links and Windows reserved filenames. Limits: 256 KiB/file, 64 KiB patch/cumulative diff, 500 files, 8 MiB workspace. All hunks are validated before mutation; exact context required. Failed cumulative validation rolls changes back. Only existing allowlisted files can change.

Filename rules cannot detect secrets deliberately embedded in ordinary source. Use a clean development repository and do not authorize test changes for the benchmark. Source snapshots and Docker output are untrusted data, not instructions.

## Docker

The trusted image contains Python, Pytest and a fixed runner. Workspace files enter through stdin tar, not a host mount. Runtime uses network none, non-root UID 65534, read-only root, no capabilities, no-new-privileges, 1 CPU, 256 MiB RAM/swap cap, 64 PIDs and bounded tmpfs. No Docker socket or host secret is mounted. Output is capped, execution has deadlines, and timeout cleanup removes the named container. Failed cleanup blocks publication. Runtime uses --pull=never; the image must already exist.

This isolates repository code from the host but is not a defense against Docker/kernel vulnerabilities. A malicious repository can manipulate its own tests; a green test result is evidence, not a proof of correctness.

## GitHub publication

Read base/head refs and verify they match the workspace revision. Prepare the exact plan, obtain backend approval, recheck refs, create a tree from approved file content, create a commit, update the branch without force, verify the resulting SHA, then create a draft PR. Changed content invalidates approval. One-use approvals and fail-closed recovery prevent blind retries; partial failures can leave a branch/commit without a PR.
