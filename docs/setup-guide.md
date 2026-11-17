# Setup and demo guide (Windows PowerShell)

## Prerequisites

Python 3.12, Node.js 22+, Git, and Docker Desktop in Linux container mode. MongoDB can be Atlas or local Compose. OpenRouter is the only LLM provider. No Redis, Kubernetes or paid enterprise services are needed. Use a regular trusted terminal, not a restricted assistant shell, for authentication and Docker access.

## Fresh checkout

```powershell
git clone https://github.com/HanishRapolu/DevPilot-AI.git
cd DevPilot-AI
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements-dev.txt
Copy-Item backend/.env.example backend/.env
cd frontend
npm ci
npm run build
cd ..
```

The GitHub remote may not yet contain final-review changes: the local review has NOT been pushed. For an existing checkout, do not overwrite your .env. Backend requirements-dev includes requirements.txt. If pip reports a dependency conflict, stop and resolve it; do not use --no-deps or assume a partial installation worked. The review environment reused an existing virtual environment; a fresh-machine installation remains a manual verification item.

## Configuration

Edit backend/.env locally. Never paste secrets into chat or commit them.

| Variable | Value/purpose |
|---|---|
| MONGODB_URI | Atlas URI or mongodb://localhost:27017 |
| MONGODB_DATABASE | devpilot (use a separate database for verification) |
| DASHBOARD_API_TOKEN | Random local bearer token |
| OPENROUTER_API_KEY | OpenRouter key |
| OPENROUTER_MODEL | openrouter/free initially; pin an explicit available free model for reproducible evaluation |
| OPENROUTER_BASE_URL | https://openrouter.ai/api/v1 |
| OPENROUTER_STRUCTURED_OUTPUTS | true; false only if intentionally using prompt-only JSON with local validation |
| GITHUB_REPOSITORY | HanishRapolu/DevPilot-AI (no URL and no trailing period) |
| GITHUB_TOKEN | Fine-grained token restricted to the chosen repository |
| REPOSITORY_SOURCE | Absolute committed local checkout path matching that repository's origin |
| REPOSITORY_ALLOWED_FILES | JSON list of exact editable source paths; keep tests read-only for the demo |
| MCP_STATE_DIR | Absolute directory OUTSIDE REPOSITORY_SOURCE |
| MCP_WORKSPACE | Leave empty for dashboard-created workspaces; CLI recovery resolves task binding |
| SANDBOX_IMAGE | devpilot-python-tests:phase2 |
| SANDBOX_TEST_PATH | Fixed relative Python test file, or . for all tests |

For the application repository's included demo use:

```dotenv
GITHUB_REPOSITORY=HanishRapolu/DevPilot-AI
REPOSITORY_SOURCE=D:/Desktop/Coding Agent/devpilot-ai
REPOSITORY_ALLOWED_FILES=["demo-repo/calculator.py"]
MCP_STATE_DIR=D:/Desktop/Coding Agent/devpilot-state
SANDBOX_TEST_PATH=demo-repo/test_calculator.py
MCP_WORKSPACE=
```

Adjust paths on another machine. Only committed HEAD files are copied; commit the demo baseline before running and ensure remote default branch points at the same revision. Do not target a stale source revision.

Generate a dashboard token with `.\.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(32))"` and paste it into .env locally. It is entered in the dashboard password field and stored for that browser tab. No API key belongs in a VITE variable.

GitHub public reads can work without a token; private reads require appropriate repository access. Approved publication needs Contents read/write, Pull requests read/write, Issues read and Metadata read. Creating a token is your action; grant access only to this repository. Publication is optional until you explicitly approve a live demonstration.

## Docker and MongoDB

For local MongoDB only (skip for Atlas):

```powershell
docker compose up -d mongodb
```

Set MONGODB_URI to mongodb://localhost:27017. This local development database binds only to loopback and uses a named volume. It has no authentication: do not expose it publicly. `docker compose down` retains the volume; do not add `-v` unless you intend to delete data.

Build the sandbox from the project root:

```powershell
docker info
docker compose --profile tools build sandbox
```

Rebuild after changes to sandbox/runner.py. The sandbox service is build-only; do not run `docker compose --profile tools up`. Testing MCP runs it with the complete fixed security policy. The API stays on the host so no Docker socket needs to be mounted into a backend container.

If Docker Hub token retrieval reports unexpected EOF, the engine is reachable but the registry connection failed. Retry on a working network and inspect Docker Desktop proxy/network settings; this is not a Python-code failure. Do not disable TLS verification.

## Start services

Terminal 1:

```powershell
cd backend
..\.venv\Scripts\python -m scripts.check_services
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The check prints progress and has 35s/105s child deadlines. Ctrl+C reports cancelled, not a service failure. It creates then removes a temporary MongoDB record and makes one small LLM request. HTTP client proxy errors occur before key validation; do not rotate keys based on that error. Atlas DNS errors require checking SRV resolution/cluster state; IP access and credentials are separate checks.

Terminal 2:

```powershell
cd frontend
npm run dev
```

Open http://localhost:5173 and enter DASHBOARD_API_TOKEN. Use one backend process, no --reload and no multiple workers during task execution. `/api/health/live` checks the process; `/api/health/ready` checks MongoDB.

## Demo walkthrough

No external issue or PR is created automatically by setup. With your permission, create a GitHub issue in the authorized repository describing BOTH included bugs: average([2,4,6]) returns 3 rather than 4, and discounted_price(200,10) returns 190 rather than 180. Check demo-repo/calculator.py/test_calculator.py for the exact baseline before writing the issue. Use the issue number in the dashboard.

1. Start Task with the repository URL and issue number.
2. Watch execution and tool events; failures should be visible rather than fabricated successes.
3. Review the diff, test output, reviewer feedback and change summary.
4. Reject first to demonstrate no publication. Start a new task for an approval demonstration.
5. Approve patch, then exact branch request, then exact publication request only after explicitly authorizing real GitHub writes.
6. Verify the draft PR URL, commit contents and passing tests manually. Publication has not been live verified during this review.

The original demo intentionally has two failing tests; it is not a failing application test suite. Five independent benchmark cases are under benchmarks/.

## Verification commands

From backend:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
..\.venv\Scripts\python -m pytest -q -m "not docker"
$env:DEVPILOT_RUN_DOCKER_TESTS='1'
..\.venv\Scripts\python -m pytest -q tests/test_mcp_integration.py -m docker
$env:DEVPILOT_TEST_MONGO='1'
..\.venv\Scripts\python -m pytest -q tests/test_mongo_restart.py
$env:DEVPILOT_LIVE_LLM_TEST='1'
..\.venv\Scripts\python -m pytest -q tests/test_workflow_live.py
..\.venv\Scripts\python -m scripts.evaluate --mode reference --output ../docs/evaluation-reference.json
..\.venv\Scripts\python -m scripts.evaluate --mode live --output ../docs/evaluation-live.json
```

Live mode consumes OpenRouter quota. Both evaluation modes use actual MCP and Docker, local issue fixtures and no GitHub writes. Real MongoDB restart tests create/drop only uniquely named verification collections. Run them against a test database. See test-report.md and evaluation.md for measured results and exclusions.

## Recovery and publication

See langgraph-workflow.md for checkpoint recovery. Never blindly replay a partially published operation. Final-review changes remain local. Before pushing: inspect `git diff`, run tests/build, check .env exclusions, then explicitly approve the commit/push. Do not force-push.
