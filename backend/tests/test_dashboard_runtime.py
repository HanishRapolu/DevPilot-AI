from unittest.mock import MagicMock

from app.workflow.runtime import Runtime


def runtime():
    instance = Runtime.__new__(Runtime)
    instance.db = MagicMock()
    return instance


def test_active_agent_is_visible_before_completion():
    instance = runtime()
    instance.events({'task_id': 'task', 'agent': 'planner', 'status': 'started'})
    update = instance.db.tasks.update_one.call_args.args[1]['$set']
    assert update['workflow.current_step'] == 'planner'
    instance.db.workflow_events.insert_one.assert_called_once()


def test_status_change_atomically_appends_history():
    instance = runtime()
    instance.db.tasks.update_one.return_value.modified_count = 1
    instance.persist_status('task', 'awaiting_approval', {'approval': {'hash': 'digest'}})
    query, update = instance.db.tasks.update_one.call_args.args
    assert query['status'] == {'$ne': 'awaiting_approval'}
    assert update['$push']['status_history']['status'] == 'awaiting_approval'
    assert update['$set']['approval']['hash'] == 'digest'
    assert instance.db.tasks.update_one.call_count == 1


def test_same_status_refresh_does_not_duplicate_history():
    instance = runtime()
    instance.db.tasks.update_one.return_value.modified_count = 0
    instance.persist_status('task', 'running', {'workflow': {'retry_count': 1}})
    update = instance.db.tasks.update_one.call_args.args[1]
    assert '$push' not in update
    assert update['$set']['workflow']['retry_count'] == 1
