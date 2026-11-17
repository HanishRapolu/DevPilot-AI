"""Five local issues through real MCP. Never creates GitHub resources.

reference: apply supplied correct patches; measures harness, not AI ability.
live: real OpenRouter agents, stopping at human approval (no publication).
"""
import argparse
import asyncio
import difflib
import json
from pathlib import Path
import tempfile
from datetime import datetime, timezone
from langgraph.checkpoint.memory import InMemorySaver
from app.config import Settings
from app.mcp_tools.workspace import Workspace
from app.services.mcp_client import MCPClientService, MCPResult
from app.services.llm import OpenRouterService
from app.workflow.graph import Workflow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['reference', 'live'], default='reference')
    parser.add_argument('--output', type=Path, default=Path('../docs/evaluation-results.json'))
    args = parser.parse_args()
    settings = Settings()
    rows = []
    cases = sorted((Path(__file__).resolve().parents[2] / 'benchmarks').glob('*/issue.json'))
    for issue_path in cases:
        issue = json.loads(issue_path.read_text())
        print('Evaluating ' + issue['id'], flush=True)
        row = {'issue': issue['id'], 'status': 'blocked', 'repairs': None, 'test_status': None,
               'mcp_calls': 0, 'mcp_successful_calls': 0, 'prepublication_complete': False}
        with tempfile.TemporaryDirectory(prefix='devpilot-eval-') as temporary:
            workspace = Workspace.create(issue_path.parent, Path(temporary), 'example/benchmark', ['calculator.py'], demo=True)
            client = MCPClientService(settings.model_copy(update={'mcp_workspace': workspace.directory, 'sandbox_test_path': '.'}))
            def tool(server, name, arguments):
                if server == 'github':
                    # Local issue fixture, explicitly not a GitHub integration measurement.
                    if name == 'get_issue': return MCPResult(ok=True, server=server, data=issue)
                    if name == 'get_repository_info': return MCPResult(ok=True, server=server, data={'default_branch': 'main'})
                    raise PermissionError('Evaluation never publishes')
                row['mcp_calls'] += 1
                result = asyncio.run(client.call(server, name, arguments))
                row['mcp_successful_calls'] += int(result.ok)
                return result
            try:
                baseline = tool('testing', 'run_tests', {})
                row['baseline_status'] = baseline.data.get('status') if baseline.ok else 'mcp_error'
                if not baseline.ok or baseline.data.get('status') != 'failed' or baseline.data.get('exit_code') != 1:
                    row['reason'] = 'Baseline must fail assertions; check Docker, image and fixture.'
                elif args.mode == 'reference':
                    before = tool('repository', 'read_file', {'path': 'calculator.py'})
                    if not before.ok: raise RuntimeError('MCP read failed')
                    fixed = (issue_path.parent / 'reference.py').read_text()
                    patch = ''.join(difflib.unified_diff(before.data['content'].splitlines(True), fixed.splitlines(True), fromfile='a/calculator.py', tofile='b/calculator.py'))
                    result = tool('repository', 'apply_patch', {'patch': patch})
                    if not result.ok: raise RuntimeError('MCP patch failed')
                    tested = tool('testing', 'run_tests', {})
                    row['test_status'] = tested.data.get('status')
                    row['status'] = 'passed' if tested.ok and row['test_status']=='passed' and tested.data.get('exit_code')==0 else 'failed'
                else:
                    def llm(prompt, schema):
                        async def invoke():
                            service = OpenRouterService(settings)
                            try: return await service.generate(prompt, schema)
                            finally: await service.close()
                        return asyncio.run(invoke())
                    graph = Workflow(llm, tool, lambda record: None, lambda *a: False).build(InMemorySaver())
                    result = graph.invoke({'task_id': issue['id'], 'repository': 'example/benchmark', 'issue_number': 1,
                        'retry_count': 0, 'approval_status': 'pending', 'task_status': 'running', 'branch': 'devpilot/evaluation'},
                        {'configurable': {'thread_id': issue['id']}, 'recursion_limit': 80})
                    row['repairs'] = result.get('retry_count', 0)
                    row['test_status'] = result.get('test_results', {}).get('status')
                    row['prepublication_complete'] = bool(result.get('__interrupt__'))
                    row['status'] = 'passed' if row['prepublication_complete'] and row['test_status']=='passed' else 'failed'
            except Exception as exc:
                row['reason'] = type(exc).__name__  # Never provider output or credentials.
        rows.append(row)
    completed = [r for r in rows if r['status'] != 'blocked']
    calls = sum(r['mcp_calls'] for r in rows)
    report = {'timestamp': datetime.now(timezone.utc).isoformat(), 'mode': args.mode,
        'model': settings.openrouter_model if args.mode=='live' else None, 'issues': rows,
        'metrics': {'evaluated': len(completed), 'blocked': len(rows)-len(completed),
            'issue_resolution_rate': sum(r['status']=='passed' for r in completed)/len(completed) if completed else None,
            'final_test_pass_rate': sum(r['test_status']=='passed' for r in completed)/len(completed) if completed else None,
            'average_repairs': sum(r['repairs'] for r in completed)/len(completed) if completed and args.mode=='live' else None,
            'mcp_protocol_success_rate': sum(r['mcp_successful_calls'] for r in rows)/calls if calls else None,
            'prepublication_completion_rate': sum(r['prepublication_complete'] for r in completed)/len(completed) if completed and args.mode=='live' else None,
            'published_prs': 0},
        'notes': 'Reference results are not AI performance. MCP protocol success does not imply Docker/test success. Live mode stops before approval; GitHub is a local fixture.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report['metrics']))


if __name__ == '__main__':
    main()
