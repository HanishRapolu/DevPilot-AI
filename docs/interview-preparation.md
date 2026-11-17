# EPAM interview preparation

## Two-minute explanation

DevPilot AI is a local software-engineering assistant that turns a GitHub issue into a proposed, tested code change, with human approval before publication. I built it as a graduate-level project to understand how to combine an LLM with deterministic engineering tools rather than simply ask a chatbot to write code.

The frontend is React with Vite and Tailwind. FastAPI creates tasks and exposes their progress, diff, tests and approval state. MongoDB stores task information and events, while an official MongoDB checkpointer stores LangGraph execution state separately.

The graph has four LLM-driven roles: planner, investigator, developer and reviewer. Investigation retrieves bounded relevant files. The developer proposes a minimal unified diff. Deterministic nodes validate the patch and run Pytest in Docker. Failed tests or reviews allow two repair retries; service failures stop with an error. The reviewer cannot override failed tests.

The agents interact with three real MCP servers over stdio: GitHub, repository and testing. The repository server restricts paths and editable files. The testing server uses a fixed command, disabled container networking, a non-root user and resource limits. Human decisions are checked by the backend and tied to the exact request. An LLM-generated approved flag has no authority.

My automated tests cover graph routing, retries, approval enforcement, API behavior and actual MCP transport. I also created five reproducible issue fixtures and a benchmark runner. I distinguish those results from live verification: the full external workflow and real draft PR publication remain unverified because the review environment cannot currently reach all required services. I would demonstrate the verified components and explain those limitations openly.

## Architecture explanation

Start at the browser: POST creates a task; polling reads state. The API submits to one background worker, keeping long LLM/container calls out of the request lifecycle. The worker copies a committed revision into a restricted task workspace. LangGraph controls transitions. Pydantic validates agent outputs. The MCP client discovers schemas and calls separate stdio servers; it does not bypass them with direct agent-side filesystem or GitHub operations.

MongoDB has two responsibilities: application queries and durable graph checkpoints. They are separate collections because a UI projection is not a graph execution log. Recovery restores the projection from the checkpoint. Local workspace and write-approval state must also survive restarts.

A publication uses GitHub's tree/commit/ref API, verifies the branch SHA, and then opens a draft PR. Human approval is checked both at the workflow and write-tool boundary. There is no claim of exactly-once remote publication: a partial failure requires inspection and manual reconciliation.

## Fifteen likely questions

1. **Why LangGraph instead of a basic while loop?** A loop can call agents, but checkpointing, explicit conditional edges, shared typed state and supported interrupt/resume would become custom machinery. LangGraph makes those transitions inspectable. For a one-shot prompt a graph would be unnecessary.

2. **Are the four agents separate models or services?** No. They are separate prompted roles and typed output contracts in one graph. They share the configured OpenRouter endpoint/model setting. The investigator uses two LLM calls: selection and synthesis. This keeps deployment simple while separating responsibilities.

3. **What is an MCP client versus an MCP server?** A server advertises tools and their schemas and executes validated requests. A client establishes the protocol session, discovers tools and invokes them. Our backend is the client; three FastMCP subprocesses are servers. Plain functions become protocol tools only when registered and served through MCP.

4. **Why stdio rather than remote HTTP MCP?** It supports local subprocess isolation without remote deployment or OAuth infrastructure. The cost is process-start overhead and a local-only topology. The environment is intentionally filtered before spawning children.

5. **How does investigation avoid loading the entire repository?** It receives a bounded file inventory, chooses up to four paths and at most three literal searches, then reads at most four files within a 20,000-character budget. Small-context limits can miss cross-file dependencies; that is an explicit MVP tradeoff.

6. **How do you validate LLM output?** The service requests JSON schema output where supported and always validates with Pydantic. Invalid/incomplete output receives bounded repair guidance. HTTP errors and timeouts have bounded retry rules. We do not accept an arbitrary string as an executable tool command.

7. **Why OpenRouter and which model?** It gives one OpenAI-compatible endpoint with configurable free/inexpensive models. The current default openrouter/free is a free router, not a fixed model. For reproducible evaluation I would pin one available model and record the model ID. There is no silent expensive fallback, and model tool calling is not required.

8. **What happens if tests fail?** The reviewer sees test evidence, but deterministic logic decides whether tests passed. A failed test or review routes back to developer with feedback, at most twice. A Docker infrastructure failure stops rather than asking the model to repair unrelated code.

9. **What is MongoDB checkpointing?** The MongoDBSaver stores graph state and pending writes keyed by a stable task thread ID. After a clean pause, a new graph runtime can resume that same thread. Task documents are separately optimized for the dashboard. A checkpoint does not automatically recover the process queue or make external side effects transactional.

10. **How is approval enforced?** The API requires a local bearer token and atomically claims the exact pending approval hash. It creates a random decision receipt in MongoDB. The graph checks that receipt against the task/payload. GitHub tools also consume a short-lived, exact write authorization. Model text cannot issue those receipts.

11. **How do you prevent duplicate PRs?** Concurrent/repeated decisions are rejected by compare-and-set. Write authorization is one-use; GitHub refs and approved content are rechecked. If a write partially succeeds, the task stops and requires reconciliation. I do not claim distributed exactly-once behavior.

12. **How do you isolate test execution?** Only a predefined Python/Pytest command runs in Docker. The container has no network, no host mounts or Docker socket, a non-root user, read-only root filesystem, restricted capabilities, memory/CPU/PID limits and timeouts. Trusted configuration chooses the test file. Docker/kernel compromise remains outside the MVP threat model.

13. **How do you handle prompt injection?** Issue/source/output content is marked untrusted, and prompts request schema-only results. The real defenses are deterministic path checks, fixed commands and backend approvals. Prompt wording alone is not sufficient. Tests verify that malicious approval text does not skip the human gate under deterministic mocked agents, not that every model is injection-proof.

14. **Why MongoDB and a single worker?** Task state, tool events and variable graph data fit documents, and the required stack includes MongoDB. One worker makes workspace locking and debugging easier for a portfolio MVP. At scale, I would consider indexes, retention and a durable queue, but those are not implemented now.

15. **What have you actually measured?** The current test report records automated passes/skips, build output and the five-case evaluation JSON. Trusted fixture validation proves the benchmark bugs and reference fixes. Docker failures blocked live evaluation, so I report no AI resolution percentage. Actual PR publication and real MongoDB cross-process recovery remain explicit verification items.

## Four evidence-based resume bullets

- Built a React/Vite dashboard and FastAPI backend for task creation, agent progress, code diffs, test results and authenticated human approval, backed by MongoDB task/event models.
- Implemented a LangGraph workflow with four LLM-driven roles, typed outputs, bounded repair retries and interrupt/resume handling; verified graph routing and approval behavior with deterministic automated tests.
- Developed three official-SDK MCP stdio servers for GitHub, repository access and Python testing; verified tool discovery, invocation and error handling through real local protocol tests.
- Added repository path and patch restrictions, exact-request approval checks, a resource-limited Docker test runner and a five-issue evaluation harness; documented external integration limits without claiming unmeasured agent accuracy.

Do not say “autonomously resolves X% of GitHub issues” or “production-ready” until the corresponding live evidence exists. Do not list a successful PR demonstration until it has been performed and inspected.
