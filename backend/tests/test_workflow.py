from types import SimpleNamespace
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
import pytest
from app.workflow.graph import Workflow


def setup(test_failures=0, reject_review=False, fail_tool=False, fail_llm=False):
    calls, events = [], []
    counter = {"tests": 0}
    def llm(prompt, schema):
        if fail_llm: raise RuntimeError("private provider failure")
        values = {"Plan": {"steps": ["Inspect mean"], "areas": ["calculator.py"]},
                  "InvestigationRequest": {"queries": ["average"], "files": ["calculator.py"]},
                  "Investigation": {"summary": "Wrong denominator"},
                  "Development": {"patch": "patch", "explanation": "Fix denominator"},
                  "Review": {"verdict": "fail" if reject_review else "pass", "feedback": "Review feedback"}}
        return schema(**values[schema.__name__])
    def tool(server, name, args):
        calls.append(name)
        if fail_tool: return SimpleNamespace(ok=False, data={})
        if name == "run_tests": counter["tests"] += 1
        data = {"get_issue": {"title": "Fix mean", "body": "Incorrect mean"},
                "get_repository_info": {"default_branch": "main"},
                "list_files": {"files": [{"path": "calculator.py"}]},
                "search_code": {"matches": [{"path": "calculator.py"}]},
                "read_file": {"content": "def average(): pass\n"}, "apply_patch": {},
                "get_diff": {"patch": "patch", "sha256": "abc", "files": ["calculator.py"]},
                "check_syntax": {"status": "passed", "exit_code": 0},
                "run_tests": {"status": "failed" if counter["tests"] <= test_failures else "passed", "exit_code": 1 if counter["tests"] <= test_failures else 0},
                "create_branch": {"status": "created"}, "create_draft_pr": {"status": "draft_created", "url": "https://github.com/example/demo/pull/1"}}
        return SimpleNamespace(ok=True, data=data[name])
    def authorize(state, payload, receipt):
        if receipt not in ("trusted-yes", "trusted-no"): raise PermissionError()
        return receipt == "trusted-yes"
    workflow = Workflow(llm, tool, events.append, authorize)
    saver = InMemorySaver()
    graph = workflow.build(saver)
    config = {"configurable": {"thread_id": "task:test"}, "recursion_limit": 80}
    state = {"task_id": "test", "repository": "example/demo", "issue_number": 1, "retry_count": 0,
             "task_status": "running", "approval_status": "pending", "branch": "devpilot/test"}
    return graph, config, state, calls, workflow, saver


def test_success_and_approval_interrupt():
    graph, config, state, calls, _, _ = setup()
    result = graph.invoke(state, config)
    assert result["__interrupt__"]
    assert "create_branch" not in calls
    result = graph.invoke(Command(resume="trusted-yes"), config)
    assert result["task_status"] == "completed" and result["pr_url"]


def test_failure_repair():
    graph, config, state, calls, _, _ = setup(test_failures=1)
    result = graph.invoke(state, config)
    assert result["retry_count"] == 1 and result["__interrupt__"]
    assert calls.count("run_tests") == 2


@pytest.mark.parametrize("kwargs", [{"test_failures": 10}, {"reject_review": True}])
def test_retry_limit(kwargs):
    graph, config, state, calls, _, _ = setup(**kwargs)
    result = graph.invoke(state, config)
    assert result["task_status"] == "failed" and result["retry_count"] == 2
    assert calls.count("run_tests") == 3 and "create_branch" not in calls


def test_human_rejection():
    graph, config, state, calls, _, _ = setup()
    graph.invoke(state, config)
    assert graph.invoke(Command(resume="trusted-no"), config)["task_status"] == "rejected"
    assert "create_branch" not in calls


def test_reconstructed_graph_resumes_checkpoint():
    graph, config, state, calls, workflow, saver = setup()
    graph.invoke(state, config)
    graph = workflow.build(saver)
    assert graph.invoke(Command(resume="trusted-yes"), config)["task_status"] == "completed"
    assert calls.count("get_issue") == 1


@pytest.mark.parametrize("kwargs", [{"fail_tool": True}, {"fail_llm": True}])
def test_external_failure(kwargs):
    graph, config, state, calls, _, _ = setup(**kwargs)
    result = graph.invoke(state, config)
    assert result["task_status"] == "failed" and "private" not in result["error"]


def test_model_approval_flag_rejected():
    graph, config, state, calls, _, _ = setup()
    graph.invoke(state, config)
    result = graph.invoke(Command(resume={"approved": True}), config)
    assert result["task_status"] == "failed" and "create_branch" not in calls
