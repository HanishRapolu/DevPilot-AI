from tests.test_api import api, PAYLOAD


def test_task_requires_token(api):
    client, db = api
    response = client.post('/api/tasks', json=PAYLOAD, headers={'Authorization': 'Bearer wrong'})
    assert response.status_code == 401
    db.tasks.insert_one.assert_not_called()


def test_repository_is_restricted(api):
    client, db = api
    response = client.post('/api/tasks', json={**PAYLOAD, 'repository_url': 'https://github.com/other/repo'})
    assert response.status_code == 403
    db.tasks.insert_one.assert_not_called()


def test_polling_diff_tests_and_result(api):
    client, db = api
    task = client.post('/api/tasks', json=PAYLOAD).json()
    task['workflow'] = {'diff': {'patch': 'actual patch', 'files': ['calculator.py']},
        'test_results': {'status': 'passed', 'exit_code': 0, 'output': '4 passed'}, 'pr_url': 'https://github.com/example/demo/pull/1'}
    db.tasks.find_one.side_effect = None
    db.tasks.find_one.return_value = task
    assert client.get(f'/api/tasks/{task["id"]}/diff').json()['patch'] == 'actual patch'
    assert client.get(f'/api/tasks/{task["id"]}/tests').json()['exit_code'] == 0
    assert client.get(f'/api/tasks/{task["id"]}').json()['workflow']['pr_url'].endswith('/1')


def test_duplicate_and_stale_approvals_rejected(api):
    client, db = api
    task = client.post('/api/tasks', json=PAYLOAD).json()
    db.tasks.update_one.return_value.modified_count = 1
    url = f'/api/tasks/{task["id"]}/approve'
    assert client.post(url, json={'approval_hash': 'a'*64}).status_code == 202
    query = db.tasks.update_one.call_args.args[0]
    assert query['status'] == 'awaiting_approval' and query['approval.hash'] == 'a'*64
    db.tasks.update_one.return_value.modified_count = 0
    assert client.post(url, json={'approval_hash': 'a'*64}).status_code == 409
    assert client.post(url, json={'approval_hash': 'a'*64, 'approved': True}).status_code == 422


def test_rejection_is_queued(api):
    client, db = api
    task = client.post('/api/tasks', json=PAYLOAD).json()
    db.tasks.update_one.return_value.modified_count = 1
    assert client.post(f'/api/tasks/{task["id"]}/reject', json={'approval_hash': 'a'*64}).status_code == 202
    client.app.state.jobs.submit.assert_called_with(task['id'], False, 'a'*64)
