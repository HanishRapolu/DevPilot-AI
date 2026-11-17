# Design decisions and limitations

| Choice | Reason | Cost/limit |
|---|---|---|
| One FastAPI app | Understandable graduate MVP | One local process/worker; no durable queue |
| React + Vite + polling | Simple independent SPA | Updates every 2.5s/4s; no streaming tokens |
| MongoDB/PyMongo | Task/event documents plus official graph checkpoint adapter | Two stores (checkpoint and UI projection) must be synchronized |
| LangGraph StateGraph | Explicit branches, bounded repair loops and resumable interrupts | More setup than a script; mutation replay requires care |
| Official stdio MCP | Real tool discovery, schemas and process boundary | Starts a process per call |
| OpenRouter only | Configurable inexpensive/free access | Free capacity and output quality vary |
| Docker on host, API on host | Avoid mounting Docker socket inside backend container | Desktop Docker must be running and accessible |
| Exact allowlist | Limit agent mutation scope | No new files, deletes, renames or binary patches |
| Three approvals | Human sees exact mutation request at each stage | More clicks than one-shot approval |
| GitHub Git Database API | Never put tokens in git command arguments | Partial writes need manual reconciliation |
| Local bearer token | Simple single-user authorization | Not multi-user identity/RBAC; protect browser and loopback |

## Model policy

Default OPENROUTER_MODEL is `openrouter/free`. Official OpenRouter information was checked during final review: it routes among available free models and filters required capabilities. It is NOT one fixed model, so results are not reproducible across provider changes. For measured interviews/benchmarks, set one explicit currently available free model ID in .env and record it. No paid/expensive fallback is implemented. Structured-output requests require provider parameter support; optional prompt-only mode still validates locally. We do not assume tool calling support because Python invokes MCP deterministically.

OpenRouter service applies bounded retries, per-attempt timeouts, output validation and bounded repair guidance. HTTP 429/408/5xx are retried; invalid credentials or unsupported requests fail promptly. Proxy initialization errors are sanitized. The pinned HTTPX version may not support the managed environment's socks5h proxy; no network controls are bypassed. Any dependency upgrade must be approved and tested.

Sources: https://openrouter.ai/openrouter/free and https://openrouter.ai/docs/guides/routing/routers/free-router .

## Not implemented / not claimed

No arbitrary-language builds, package installation in task containers, remote MCP deployment, OAuth, multi-user authentication, distributed workers, automatic crash recovery, automatic publication reconciliation, proof against prompt injection, production deployment, or verified autonomous issue-resolution rate. No real PR has been created during the final review. Live service failures are recorded separately from deterministic test results.

## Security model

Issue text is untrusted; system/schema instructions and role prompts mark it as data. Deterministic path/argument checks, container isolation and backend approvals enforce boundaries even if the LLM follows malicious text. The prompt-injection test proves that forged issue approval text cannot skip the human interrupt under mocked agents; it does not prove an LLM will always ignore adversarial instructions. Checkpoints may contain private code and should be protected like the repository.
