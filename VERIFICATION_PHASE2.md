# Phase 2 verification — November 12, 2026

**Implementation is present; live MCP/Docker verification is pending.**

## Actual results

| Check | Result |
| --- | --- |
| Phase 2 unit/security tests plus existing synchronous/configuration tests | **58 passed, 2 skipped in 20.08 seconds** |
| Symlink escape test | Skipped because this Windows environment cannot create symlinks; hard-link rejection test passed |
| Real MCP integration module | Skipped at import because official `mcp` SDK is not installed |
| Python compilation (backend app/scripts and sandbox) | Passed |
| Credential-free MCP demo | Exited with structured `missing_dependency`; no successful MCP call is claimed |
| Demo isolated workspace creation | Succeeded; source unchanged; demo cannot publish GitHub writes |
| Docker engine inspection | Access denied to Docker Desktop Linux-engine named pipe in this execution environment |
| Real Docker test run | Not performed; image not built or pulled |
| GitHub API tests | Passed using `httpx.MockTransport`; no actual GitHub writes |
| Environment secrecy | Existing credentials preserved; `backend/.env` verified ignored by Git |

The passing tests cover file access/search, traversal/hidden/protected paths,
Windows device names and alternate streams, file/patch limits, hard links,
atomic multi-file patch validation, patch context, exact and expiring one-use
approvals, branch write approval, changed-patch invalidation, GitHub issue reads,
sanitized errors, read/write configuration independence, commit/ref/PR ordering,
Docker command restrictions, timeout cleanup, client argument schemas, and
subprocess secret separation. Docker subprocess results are mocked in these tests.

## Commands executed

```powershell
python -m pip show mcp
docker info --format '{{.ServerVersion}}'
python -m scripts.prepare_workspace --demo
python -m scripts.mcp_demo
python -m pytest -q tests/test_mcp_integration.py
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_phase2.py tests/test_core.py tests/test_llm.py::test_no_credentials_or_other_provider tests/test_mcp_integration.py
python -m compileall -q backend/app backend/scripts sandbox
git check-ignore backend/.env
git status --short
```

The combined test command ran from `backend`; the compile command ran from the
project root. `rg` was unavailable, so project inspection used PowerShell file
listing and targeted source reads. No secrets were printed.

No dependency installation was attempted in Phase 2: the user's instruction
requires approval before new dependency installs. `mcp==1.28.0` and the existing
`jsonschema==4.23.0` are declared in backend requirements. The SDK is pinned to
the official v1 FastMCP/ClientSession APIs documented by that release.

## Remaining verification steps

1. Approve/install `python -m pip install -r requirements-dev.txt` from `backend`.
2. Run `python -m pytest -q tests/test_mcp_integration.py -m "not docker"` and
   `python -m scripts.mcp_demo` in a terminal where asyncio works. This must show
   actual stdio discovery and a successful `read_file` invocation.
3. Build the trusted image: from the project root,
   `docker build -t devpilot-python-tests:phase2 ./sandbox`. This downloads/builds
   dependencies and needs user approval. Then run the documented opt-in Docker test.
4. For the real authorized repository, privately configure `REPOSITORY_SOURCE`
   and exact `REPOSITORY_ALLOWED_FILES`, prepare its workspace, and set the printed
   `MCP_WORKSPACE`. A GitHub token is optional for public reads; approved writes
   require a fine-grained token scoped only to that repository.

Do not treat these pending checks as passing. Phase 1's full asyncio suite and
live service checks retain their previously documented limitations. No LangGraph
workflow or Phase 3 code has been started.
