# Phase 3: LangGraph workflow

The implementation is in `backend/app/workflow/`: `models.py` defines typed state
and validated agent outputs; `graph.py` builds a real LangGraph `StateGraph`;
`runtime.py` connects existing OpenRouter/MCP services, MongoDB checkpoints,
events, task status and trusted human decisions. `scripts/run_workflow.py` is the
human-operated entry point. No dashboard or unauthenticated approval API was added.

## Graph

START → load_issue → planner → investigator → developer → validate_patch →
test_runner → reviewer. Passing tests AND passing review lead to human_approval.
Otherwise retry increments the repair counter and returns to developer, up to two
repairs after the first attempt. Exhaustion ends as failed with review feedback.
An LLM, MCP, scope or validation exception fails closed with a sanitized error.

Human rejection ends without publication. Human approval leads to create_branch,
then create_pr, then END. These nodes use GitHub MCP exclusively; Phase 2 performs
the actual commit, non-force remote ref update, verification and draft PR creation.
The reviewer cannot override syntax/test failure or a nonzero test exit code.

All four agents call the existing OpenRouter service and configured model. The
investigator first asks the LLM for up to three literal searches and four paths,
then reads a maximum of four small files (20,000 characters total). It never sends
the entire repository's source to the LLM. Developer repairs reread current files.
Repository patch tools enforce the existing file allowlist and strict unified diff
validation. All repository/GitHub/testing operations use MCPClientService.

## Checkpointing and authorization

Production uses the official `langgraph-checkpoint-mongodb` MongoDBSaver with
separate `workflow_checkpoints` and `workflow_checkpoint_writes` collections.
Task documents remain in `tasks`. Stable thread IDs are `task:<task UUID>`.
Tests use LangGraph InMemorySaver and real compiled graphs, with mocked LLM/tool
dependencies. A reconstructed graph resumes the same saved interrupt.

The CLI displays the pending payload and requires an interactive terminal to
APPROVE or REJECT. Runtime stores a random receipt in `workflow_decisions`, bound
to the task and exact interrupt payload hash. The graph checks that record on resume;
an arbitrary boolean or model-generated approval object is rejected. The runtime
is trusted backend code, not an agent tool. No agent can mint or approve receipts.

Phase 2's stronger exact-write controls are retained: there are currently three
review points (patch, branch request, exact PR publication request). Each uses a
supported LangGraph interrupt/Command resume. The CLI displays the exact Phase 2
plan for write approval. Rejection at the PR stage may leave the already-approved
branch, but publishes no patch or PR. Combining these into a single atomic approval
would require a dedicated publication-plan MCP tool, which is not implemented.

Workspaces are bound to one task and runs are serialized with a local lock. This
is a single-process/single-host MVP. Do not call Runtime.run from an untrusted
route, give agents host shell access, or allow them to edit control records.

## Usage

Existing requirements now declare LangGraph and the MongoDB checkpointer. Install
new dependencies only after approval. Keep secrets in the existing ignored `.env`.
Prepare a real Phase 2 workspace matching GITHUB_REPOSITORY and configure its
MCP_WORKSPACE. Create a task through the existing API with a valid issue number.

From `backend`:

Use `..\.venv\Scripts\python` in place of `python` in the commands below.
The approved checkpoint dependency installation is in that local environment.

```powershell
python -m scripts.run_workflow TASK_UUID
# Inspect a pending interrupt without approving:
python -m scripts.run_workflow TASK_UUID
# Display and decide on the pending request interactively:
python -m scripts.run_workflow TASK_UUID --decide
```

The command blocks during execution; there is no background queue. On restart it
loads the same checkpoint. Mid-publication crashes are deliberately fail-closed:
Phase 2 one-use approvals can be consumed before the next checkpoint is written.
Inspect GitHub manually before recovery; automatic exactly-once publication and
reconciliation of partially completed writes are not claimed.

`workflow_events` stores agent/node name, status, timestamps, retry attempt, tool
name and sanitized error type. It does not store prompts, credentials, raw provider
errors or tool arguments. Checkpoints necessarily contain issue details, bounded
code context and patches; use a development repository and restrict database access.

## Verification commands

```powershell
python -m pytest -q tests/test_workflow.py
$env:DEVPILOT_LIVE_LLM_TEST="1"
python -m pytest -q tests/test_workflow_live.py
```

Mocked graph tests cover success, deterministic test repair, retry exhaustion,
review rejection, human interrupt/rejection, checkpoint resume after rebuilding
the graph, MCP failure, LLM failure, and forged approval rejection. Live MongoDB
restart/persistence, live stdio tools, Docker and real GitHub publication must be
verified separately; passing mocked graph tests does not establish those paths.
