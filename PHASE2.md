# Phase 2 — Local MCP tools

This extends the existing React/FastAPI/MongoDB/OpenRouter project. The three
tool servers use **FastMCP from the official `mcp==1.28.0` Python SDK**, with
local stdio transport. The version is deliberately pinned to the documented
v1 API; upgrading to SDK v2 requires changing imports and client APIs.

Implementation is present. Protocol and Docker verification must be completed
on a machine with the SDK installed and access to Docker. See `VERIFICATION_PHASE2.md`
for actual results; unit tests do not establish that stdio or Docker ran.

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `backend/app/mcp_tools/servers/github.py` | GitHub MCP tool registration and stdio entry point |
| `backend/app/mcp_tools/servers/repository.py` | Repository MCP tool registration and stdio entry point |
| `backend/app/mcp_tools/servers/testing.py` | Testing MCP tool registration and stdio entry point |
| `backend/app/mcp_tools/github.py` | Official GitHub REST API and approved publication sequence |
| `backend/app/mcp_tools/workspace.py` | Sanitized checkout snapshots, containment, file policy |
| `backend/app/mcp_tools/repository.py` | File listing/reading, literal search, strict unified patches, diff |
| `backend/app/mcp_tools/testing.py` | Fixed Docker invocation, bounded I/O, deadlines, result persistence |
| `backend/app/mcp_tools/common.py` | Structured results, safe errors, cross-process locks |
| `backend/app/services/mcp_client.py` | Real MCP initialize/discover/call gateway for future LangGraph nodes |
| `backend/app/services/approvals.py` | Exact, expiring, single-use human approvals outside the checkout |
| `backend/scripts/prepare_workspace.py` | Trusted setup of an isolated workspace |
| `backend/scripts/approve_write.py` | Human-only local approval review |
| `backend/scripts/mcp_demo.py` | Credential-free real stdio discovery and invocation demonstration |
| `sandbox/` | Trusted Python/Pytest container image and runner |
| `backend/tests/test_phase2.py` | Security, repository, approvals, mocked GitHub/Docker unit tests |
| `backend/tests/test_mcp_integration.py` | Real stdio tests and opt-in Docker-via-MCP test |

The server modules are genuine MCP adapters: they register typed tools and run
`mcp.run(transport="stdio")`. Implementation functions exist for maintainability
and unit testing. **Agents must call `MCPClientService`**, never those implementation
classes. No agent graph or new agent HTTP API is implemented in this phase.

## Available tools

| Server | Tool | Arguments |
| --- | --- | --- |
| GitHub | `get_issue` | `owner`, `repo`, `issue_number` |
| GitHub | `get_repository_info` | `owner`, `repo` |
| GitHub | `create_branch` | `branch`, `base="main"` |
| GitHub | `create_draft_pr` | `branch`, `base`, `title`, `body=""` |
| Repository | `list_files` | none |
| Repository | `read_file` | `path` |
| Repository | `search_code` | `query` (literal text) |
| Repository | `apply_patch` | `patch` (unified diff) |
| Repository | `get_diff` | none |
| Testing | `run_tests` | none |
| Testing | `get_test_results` | none |
| Testing | `check_syntax` | none |

There is deliberately **no** `approved`, `command`, `cwd`, repository-root,
container-image, or credential argument in any tool. These come from trusted
backend configuration or are fixed by code.

## Installation and local verification

Obtain approval before installing dependencies in an assisted session. From
`backend`, use your project's Python interpreter:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q tests/test_phase2.py
python -m pytest -q tests/test_mcp_integration.py -m "not docker"
python -m scripts.mcp_demo
```

The demo uses an isolated temporary copy of the bundled fixture and no GitHub
credentials. It discovers all 12 tools over stdio, reads `calculator.py`, and
demonstrates rejection of `../.env`. It does not contact GitHub or open PRs.
Its outer process deadline also covers the Windows asyncio startup problem
observed in the assisted runtime. If the SDK is missing it exits immediately.

Build the trusted sandbox image from the project root (downloads a base image
and installs Pytest during build; obtain approval first):

```powershell
docker build -t devpilot-python-tests:phase2 ./sandbox
cd backend
$env:DEVPILOT_RUN_DOCKER_TESTS="1"
python -m pytest -q tests/test_mcp_integration.py -m docker
```

Docker Desktop must be running in Linux-container mode and accessible to the
terminal user. Docker requires **no API key**. Tools use `--pull=never`, so they
cannot trigger image downloads. Repository dependencies are not installed at
test time; this MVP's sandbox supports Python standard library and Pytest only.
The demo's expected result is **two failing and two passing tests**. Syntax should
pass. Test failures are structured execution results, not MCP transport errors.

## Configure your authorized repository

Keep the existing MongoDB/OpenRouter settings. Edit `backend/.env` locally:

```dotenv
GITHUB_REPOSITORY=owner/repository
GITHUB_TOKEN=
REPOSITORY_SOURCE=D:/path/to/existing/clean-checkout
REPOSITORY_ALLOWED_FILES=["calculator.py","test_calculator.py"]
MCP_WORKSPACE=
MCP_TIMEOUT_SECONDS=150
SANDBOX_IMAGE=devpilot-python-tests:phase2
SANDBOX_TIMEOUT_SECONDS=60
```

Use your actual exact file paths in `REPOSITORY_ALLOWED_FILES`. The checkout's
origin must be `https://github.com/owner/repository[.git]` or the corresponding
`git@github.com:owner/repository[.git]`. Its HEAD must be a real commit. Setup copies
committed HEAD contents; local edits and untracked files are never copied. Commit
any intended changes yourself before preparation. Setup reads Git objects
without applying checkout filters, and disables fsmonitor and hooks for its Git
commands. It avoids `git status`, which could invoke configured clean filters.
It does not clone or alter the source checkout.

Then run:

```powershell
python -m scripts.prepare_workspace
```

Put the printed path into `MCP_WORKSPACE`. Each preparation creates a fresh
UUID directory under `backend/.devpilot/workspaces`. Its `repo/` is the isolated
working copy; `baseline/` and `manifest.json` are outside tool-visible paths.
The manifest pins the repository, base commit, copied files and editable files.
For repository-only experimentation use `--demo`; demo workspaces cannot perform
GitHub writes even if a token is configured.

For public read operations, a GitHub token is optional. For private reads, use
a fine-grained PAT limited to this repository, with Metadata, Contents and Issues
read access. To enable approved writes, grant Contents read/write and Pull
requests read/write. Store the token only in `backend/.env`; never in a Git remote
URL, frontend environment, command argument, or chat. No real GitHub writes have
been performed by automated tests.

## How the backend connects

`MCPClientService` launches the current Python interpreter with one of:

```text
python -m app.mcp_tools.servers.github
python -m app.mcp_tools.servers.repository
python -m app.mcp_tools.servers.testing
```

It uses the SDK's `stdio_client` and `ClientSession`, performs `initialize`,
discovers `list_tools`, validates arguments against the advertised JSON schema,
and calls `call_tool`. Unknown keys/tools are rejected. Each operation owns and
closes its subprocess/session to keep lifecycle understandable. Connection and
operation deadlines return structured errors. No arbitrary server executable or
module can be supplied by a model.

Future LangGraph node example (requires a configured workspace and installed SDK):

```python
from app.services.mcp_client import MCPClientService

client = MCPClientService()
tools = await client.discover("repository")
result = await client.call("repository", "read_file", {"path": "calculator.py"})
if not result.ok:
    # Handle result.error; never pretend the tool succeeded.
    ...
else:
    source = result.data["content"]
```

Successful result shape (illustration, not a claim that the current runtime ran it):

```json
{"ok":true,"server":"repository","tool":"read_file","data":{"path":"calculator.py","content":"..."},"error":null}
```

Only the GitHub child receives its GitHub token. Repository and testing children
receive no API keys or MongoDB URI. Servers do not read `.env` themselves. Stdout
is reserved for MCP traffic; local server stderr is not returned to agents.

## Approval and publication flow

1. Call `create_branch` with a dedicated `devpilot/name` target and base branch.
   The server compares the remote base SHA with the workspace revision and returns
   `status=approval_required` plus a content-derived request ID. It performs no write.
2. The human runs `python -m scripts.approve_write REQUEST_ID` in their terminal.
   The command displays exact JSON with escaped control characters, requires a TTY,
   and requires typing `APPROVE REQUEST_ID`. It is not an MCP tool or HTTP endpoint.
3. Retry the same call. The server atomically consumes the approval once, then
   creates the branch at the approved SHA.
4. Use the Repository MCP tools to make and inspect the patch. Request `create_draft_pr`.
   A separate approval binds the repository, branches, base/head SHAs, full patch,
   file contents, PR title and body. Changing any of these requires a new approval.
5. After approval and an unchanged retry, the server rechecks remote refs, creates
   a Git tree from the approved file contents on the existing base tree, creates a
   commit, and updates **only** the intended branch with `force=false`. This publishes
   the commit using GitHub's Git Database API rather than a token-bearing `git push`.
6. It reads the branch ref back and verifies the published commit SHA. Only then
   does it call GitHub's pull-request endpoint with `draft=true`.

Approvals expire after 30 minutes and cannot be replayed. They are transient local
JSON control records under `.devpilot/approvals`, outside repository tools and the
container; MongoDB remains the application task database. The local OS user is the
trust boundary. Do not give an agent arbitrary host shell access or access to the
approval directory. The human approval command must never become an agent tool.

GitHub writes are intentionally not automatically retried. If GitHub succeeds but
the response is lost, inspect the branch/PR manually before any new approval. A
failure after publishing a commit may leave a branch without a PR. The consumed
approval prevents accidental duplicate publication. This MVP does not implement
distributed transactions or automatic recovery of partially completed publications.

## Security boundaries and limits

- Exact repository allowlist and dedicated `devpilot/` write branches.
- Only manifest-listed text files can be read; exact allowlist controls edits.
- All hidden paths, `.env` variants, `.git`, `.github`, `.aws`, credential-related
  filenames, executable/binary types, Windows device names, alternate data streams,
  traversal, symlinks, junctions, and hard links are rejected.
- 256 KiB per file, 64 KiB per patch and cumulative diff, 500 files, 8 MiB total
  workspace; search returns at most 100 matches with bounded line text.
- Patches support modifications of existing UTF-8 files. Add/delete/rename, binary,
  mode changes, and no-newline markers are rejected. Hunk positions, counts, and
  context must match. All edits are validated before writes; write failures roll back.
- Cross-process locks serialize workspace operations. A crashed process may leave
  a lock; inspect before removing it manually. No automatic stale-lock override.
- Snapshot transfer uses stdin tar bytes, not a host bind mount. Only regular safe
  files are extracted; no host secrets or Docker socket enter the container.
- Docker uses no network, UID/GID 65534, read-only root filesystem, dropped
  capabilities, no-new-privileges, 1 CPU, 256 MiB memory, and 64 PIDs. Writable
  temporary filesystems are bounded. Timeouts force container removal, with cleanup
  status returned. Container output is bounded and always marked untrusted.
- Syntax checking uses `ast.parse` in Docker. Pytest executes repository code only
  in Docker, with a fixed trusted config and plugin autoload disabled. Test output
  can still be misleading because the repository under test is untrusted.
- Filename filtering cannot discover secrets deliberately embedded in ordinary
  source files. Authorize a clean development checkout without embedded credentials.
- This is a local single-user MVP, not a sandbox against a malicious host account
  or a Docker/kernel escape. No remote MCP, OAuth service, queues or extra database
  infrastructure was added.

Official references used:

- https://pypi.org/project/mcp/1.28.0/
- https://docs.github.com/en/rest/git/refs
- https://docs.github.com/en/rest/git/trees
- https://docs.github.com/en/rest/pulls/pulls
