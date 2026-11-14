# Phase 4 verification - 2026-11-13

## Measured results

From `backend`, using the project virtual environment:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
..\.venv\Scripts\python -m pytest -q tests/test_api.py tests/test_dashboard_api.py tests/test_core.py tests/test_workflow.py
# 34 passed, 1 warning in 15.96s

..\.venv\Scripts\python -m pytest -q -m 'not docker and not integration'
# 104 passed, 2 skipped, 1 deselected, 1 warning in 75.96s
```

The full suite includes real local MCP stdio discovery/invocation. API tests use a mocked database and worker; graph tests use deterministic mocked LLM and external tool results. These are not a live end-to-end demonstration. The warning is an upstream Starlette/AnyIO deprecated alias.

New checks cover token enforcement, repository restriction, diff/test/result API projections, atomic approval claims, stale/duplicate submissions, rejection dispatch, active agent updates and status history.

From `frontend`:

```powershell
npm run build
# Initial attempt failed because dependencies were missing.
# After authorized installation and patched dependency updates: PASSED.
# TypeScript passed; Vite transformed 61 modules and built in 3.13s.
```

User approved installation. Ran `npm install`, then `npm audit --json`. Updated to `react-router-dom@7.18.5` and `diff@9.0.0` to resolve reported advisories. The final install audit reports **0 vulnerabilities**. The package lock is updated.

Inspected the real dashboard in the in-app browser, including the narrow layout, inputs and backend-error state. Populated task routes have not been visually verified because external services are unavailable.

After changing MongoClient startup to `connect=False`, FastAPI starts successfully even when Atlas SRV DNS fails. Re-ran API/dashboard runtime tests: **20 passed**, one upstream warning, in 15.30s. Browser polling reaches FastAPI and receives HTTP 401 without a dashboard token.

Live checks: `python -m scripts.check_services` reports MongoDB `dns_resolution_failed` and OpenRouter `ValueError` (the installed HTTP client rejects the environment's `socks5h` proxy scheme). `docker info` reports access denied to the Docker Desktop Linux engine. No proxy/network protection was bypassed.

A local check confirmed `DASHBOARD_API_TOKEN` is configured in the ignored backend environment file without printing its value.

## Remaining verification

- Inspect the populated execution, review and result pages once services are reachable.
- Verify live React -> API -> MongoDB -> LangGraph -> MCP -> Docker/OpenRouter workflow with the user's configured services.
- Exercise real approval/rejection and restart/checkpoint persistence.
- Explicitly authorize a demonstration GitHub publication, inspect the resulting commit/draft PR and verify duplicate-submission behavior. No real GitHub write was performed during tests.

Phase 4 is not yet fully verified. See PHASE4.md for setup and operational limitations.
