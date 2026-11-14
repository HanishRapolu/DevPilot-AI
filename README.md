# DevPilot AI

See [PHASE2.md](PHASE2.md) for MCP and sandbox setup, [PHASE3.md](PHASE3.md) for LangGraph and checkpoints, and [PHASE4.md](PHASE4.md) for the dashboard, API authorization, approval flow and current limitations.

A graduate portfolio project using React, FastAPI, MongoDB, OpenRouter, LangGraph and genuine local MCP servers. Creating a task queues a real agent workflow. The dashboard implementation covers execution, review and results; dependencies are installed and its production build passes. Live end-to-end verification is blocked by service connectivity/access. GitHub publication is implemented but has not been live verified.

## Layout and decisions

| Path | Purpose |
| --- | --- |
| `frontend/src/App.tsx` | Responsive dashboard: task creation, pagination, details, activity, loading/error states |
| `frontend/src/api.ts` | Typed API contract and bounded HTTP requests |
| `frontend/src/styles.css` | Tailwind and shared input/panel styles |
| `frontend/vite.config.ts` | React/Tailwind plugins and local API proxy |
| `backend/app/main.py` | App factory, lifecycle, CORS, sanitized database errors |
| `backend/app/config.py` | Validated environment settings and secret fields |
| `backend/app/models.py` | Task request, stored task, event, and pagination schemas |
| `backend/app/database.py` | Request-scoped access to the shared PyMongo database |
| `backend/app/api/` | Modular task and health routes |
| `backend/app/services/llm.py` | OpenRouter-only client with timeout/retry/schema validation |
| `backend/tests/` | Isolated API and LLM unit tests; no credentials or running DB required |
| `backend/scripts/check_llm.py` | Explicit live connectivity check using a validated output schema |
| `demo-repo/` | Two deliberately buggy Python functions, four tests, manual Docker runner |
| `compose.yaml` | Optional local MongoDB with persistent volume and loopback-only port |

The frontend calls one backend; that backend uses one MongoDB database. Synchronous PyMongo routes run in FastAPI's worker thread pool. The MongoClient is shared per application lifetime and closed at shutdown. UUID task IDs are MongoDB primary keys. Events are embedded in task documents so creation and the first event are one atomic insert without requiring a replica set. Later long-running histories can move into a separate collection. No broad repository/service abstraction is needed yet.

The reusable async LLM service is independent of HTTP routing. LangGraph nodes invoke it and use official MCP stdio servers for controlled repository, GitHub and testing operations. Backend-issued human approvals gate GitHub writes. A single background worker keeps execution separate from polling requests.

## Prerequisites and setup (PowerShell)

Python 3.12+, Node 22, and MongoDB are required. Docker Desktop is needed for the optional local DB and manual fixture container. Obtain approval before running dependency installation or Docker builds/pulls in an assisted session.

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements-dev.txt
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
if (!(Test-Path frontend/.env)) { Copy-Item frontend/.env.example frontend/.env }
cd frontend
npm install
npm run build
```

The frontend includes `package-lock.json`; use `npm ci` for reproducible subsequent installs. The production build has been verified with `npm run build`.

For this project, configure your MongoDB Atlas URI in `backend/.env`.
The checked-in example contains placeholders, not a working connection. Replace
them with the connection string from your cluster, including your database-user
password. Never paste it into chat. The local `.env` files are ignored by Git.
`GITHUB_TOKEN`, `GITHUB_REPOSITORY`, and `SANDBOX_*` entries are reserved for later
phases and are not used by Phase 1. Docker is intended for sandboxed execution;
it is not required for an Atlas database.

If you ever choose local MongoDB instead, the optional Compose alternative is:

```powershell
docker compose up -d mongodb
```

For that alternative, change `MONGODB_URI` to `mongodb://localhost:27017`.
MongoDB Compose is a local development instance without authentication; do not expose it to a public interface.

Start the API from `backend`:

```powershell
..\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the UI in another terminal from `frontend`:

```powershell
npm run dev
```

Visit http://localhost:5173 and http://127.0.0.1:8000/docs. Use `localhost` for the frontend to match the default CORS setting. A production frontend needs `VITE_API_BASE_URL` pointing to its backend; Vite's development proxy does not exist in the built bundle.

## Configuration and model choice

Never paste secrets into chat or commit `.env`. Edit `backend/.env` locally. The frontend contains only the public backend URL; no API key or DB URI belongs in a `VITE_*` variable.

| Variable | Default / behavior |
| --- | --- |
| `MONGODB_URI` | `mongodb://localhost:27017` |
| `MONGODB_DATABASE` | `devpilot` |
| `OPENROUTER_API_KEY` | Empty; task CRUD works without it; LLM calls require it |
| `OPENROUTER_MODEL` | `openrouter/free` |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1`; non-OpenRouter URLs rejected |
| `OPENROUTER_STRUCTURED_OUTPUTS` | `true`; requests strict JSON schema and compatible provider routing |
| `LLM_TIMEOUT_SECONDS` | 30 per attempt, including an outer async deadline |
| `LLM_MAX_ATTEMPTS` | 3 total attempts, not 3 additional retries |
| `CORS_ORIGINS` | JSON array of permitted frontend origins |

Official OpenRouter sources checked on November 12, 2026:

- [Free models and free router](https://openrouter.ai/collections/free-models): `openrouter/free` selects available free models matching requested capabilities. This avoids pinning a disappearing free model. It is not a deterministic model choice and free capacity/rate limits can interrupt requests.
- [Structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs): compatibility varies by model/provider; require compatible routing and still validate locally.
- [Model catalog API](https://openrouter.ai/docs/api/api-reference/models/get-models): inspect available IDs and supported parameters before changing the model.

No paid fallback is selected automatically. If free capacity proves unsuitable, choose a verified inexpensive model explicitly via the environment. No tool-calling capability is assumed. For a model without schema support, explicitly set `OPENROUTER_STRUCTURED_OUTPUTS=false`; prompt-only JSON is still validated with Pydantic and may fail. Use output models with `extra="forbid"` and required fields for strict-schema compatibility.

Transient connection errors, timeouts, HTTP 408/429/5xx, and malformed or truncated outputs are retried with bounded exponential delays. Other 4xx errors fail immediately. Raw provider errors and model output are not exposed in error messages. Requests have a 2048-token output cap. No runtime LLM calls occur merely by starting the application or saving a task.

Explicit live check after configuring a key (consumes your model quota):

```powershell
# From backend
..\.venv\Scripts\python -m scripts.check_llm
```

For a combined Atlas persistence and OpenRouter check, run `python -m scripts.check_services`
from `backend`. It creates one temporary task, reads it using a fresh MongoDB client,
and deletes that exact task. It also requests a small validated LLM response. Output
contains only sanitized statuses; each check runs in a child process with a deadline.

## API

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/api/tasks` | Validate and atomically save task plus creation event; 201 |
| GET | `/api/tasks?limit=20&offset=0` | Paginated newest-first tasks; limit 1–100 |
| GET | `/api/tasks/{uuid}` | Retrieve task; 404 if missing, 422 if invalid ID |
| GET | `/api/tasks/{uuid}/events` | Retrieve task activity |
| GET | `/api/health/live` | Process health without contacting MongoDB |
| GET | `/api/health/ready` | MongoDB ping; 503 when unavailable |

Task example:

```json
{"title":"Fix average calculation","repository_url":"https://github.com/owner/repository","issue_number":1,"description":"The mean of [2, 4, 6] should be 4."}
```

GitHub URLs must match the backend's authorized repository. Task endpoints require the local dashboard bearer token; bind to loopback. API listing uses offset pagination and count is not a transactional snapshot under concurrent writes. Larger datasets will need an index on creation time and cursor pagination.

## Verification

```powershell
# From backend: must pass
python -m pytest -q
# From frontend: must pass after dependency installation
npm run build
# From demo-repo: intentionally produces 2 failures and 2 passes
python -m pytest -q
```

Backend tests include database/LLM doubles and real stdio MCP protocol tests; they do not prove live MongoDB/OpenRouter/GitHub availability. For a live persistence check, finish or pause a task, restart the API, and retrieve it again. Check readiness with MongoDB stopped and running. Testing MCP uses Docker; actual container execution is a separate opt-in integration check. See the phase verification documents for measured results.
