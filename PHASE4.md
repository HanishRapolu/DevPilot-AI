# Phase 4 dashboard

## Pages

- `/`: authorized repository and issue input, task creation, recent tasks (4-second polling).
- `/tasks/:id`: issue details, current agent, step statuses, retries, activity timeline (2.5-second polling).
- `/tasks/:id/review`: unified original/modified diff, changed files, tests, review feedback and human decisions.
- `/tasks/:id/result`: final status, changed files, investigation summary, test output and verified-format GitHub PR link when the backend has one.

The frontend uses React Router, Fetch and the lightweight `diff` parser. It renders only API data. Errors, empty states and loading states are included; polling stops at terminal statuses.

## Local setup

Frontend dependencies are installed and the production build passes. To reproduce: `cd frontend`, then `npm ci` and `npm run build`. React Router 7.18.5 and diff 9.0.0 replace the initially selected versions following the dependency audit.

The ignored `backend/.env` contains `DASHBOARD_API_TOKEN`. Copy that value locally into the dashboard's password field and click Connect. Never paste it into chat or put it in a VITE variable. The browser keeps it in sessionStorage for that tab; use only a trusted local browser. This is a single-user local access gate, not production authentication.

Run the backend from `backend` with `..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`. Run `npm run dev` from `frontend`; Vite proxies `/api` to FastAPI. Keep one backend process, with no auto-reload during workflows.

Existing configuration is still required: MongoDB URI, OpenRouter credentials/model, authorized GitHub repository and appropriate GitHub token, committed local repository source and allowed files, Docker engine and the test image described in PHASE2.md. Configure secrets only in the ignored backend `.env`.

## Backend integration

All `/api/tasks` endpoints require `Authorization: Bearer <DASHBOARD_API_TOKEN>`.

| Endpoint | Behavior |
| --- | --- |
| POST /api/tasks | Validates authorized repository and issue; inserts task and queues real workflow |
| GET /api/tasks | Recent persisted task list |
| GET /api/tasks/{id} | Task plus workflow projection and approval request |
| GET /api/tasks/{id}/events | Persisted agent/tool activity |
| GET /api/tasks/{id}/diff | Actual isolated workspace diff projected by LangGraph |
| GET /api/tasks/{id}/tests | Actual Testing MCP result projected by LangGraph |
| POST /api/tasks/{id}/approve | Claims the exact pending approval hash and resumes with a trusted decision receipt |
| POST /api/tasks/{id}/reject | Same authorization and atomic claim; resumes with rejection |

`services/jobs.py` runs one background worker and prepares/reuses a task-specific isolated workspace. `workflow/runtime.py` streams LangGraph state into task documents, stores status history and updates active-agent status. Existing MongoDB checkpoints remain separate. Agent operations continue through MCP.

There are three human checkpoints: patch review, branch creation and exact PR publication request. Review the displayed request at each pause. Approvals cannot be supplied by an agent. Atomic compare-and-set rejects duplicate/stale submissions. Existing one-use write authorizations prevent automatic duplicate publication. Publication commits the approved tree through GitHub's Git Database API and updates the branch before creating the draft PR; it does not run a host `git push` command.

## Operational limits

- The worker queue is in-process. A backend crash can leave queued/running tasks stranded; checkpoint recovery remains an operator action via the Phase 3 CLI, not automatic queue recovery.
- Partial GitHub publication failures stop closed. Inspect GitHub before manual recovery; do not create a replacement task blindly. This is not a distributed exactly-once guarantee.
- A task list returns complete task projections; pagination is available but this is intended for a small portfolio workload.
- The dashboard's responsive layout and error state were inspected in the browser. Populated execution/review/result pages and live end-to-end verification remain outstanding: MongoDB DNS fails, OpenRouter's HTTP client rejects this session's proxy scheme, and Docker engine access is denied. Automated API/graph tests use mocks for external services. No actual PR creation has been verified.
