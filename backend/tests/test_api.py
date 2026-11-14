from copy import deepcopy
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.config import Settings
from app.main import create_app


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr("app.main.Jobs", MagicMock())
    db = MagicMock()
    stored = {}

    def insert(document):
        stored[document["_id"]] = deepcopy(document)

    db.tasks.insert_one.side_effect = insert
    db.tasks.find_one.side_effect = lambda query: deepcopy(stored.get(query["_id"]))
    db.workflow_events.find.return_value.sort.return_value.limit.return_value = []
    with TestClient(create_app(Settings(_env_file=None, dashboard_api_token="test-only", github_repository="example/demo"), database=db), headers={"Authorization": "Bearer test-only"}) as client:
        yield client, db


PAYLOAD = {"title": "Fix average", "repository_url": "https://github.com/example/demo",
           "issue_number": 1, "description": "Average returns the wrong value"}


def test_create_get_and_events(api):
    client, db = api
    response = client.post("/api/tasks", json=PAYLOAD)
    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "pending"
    assert len(task["events"]) == 1
    assert client.get(f'/api/tasks/{task["id"]}').json() == task
    assert client.get(f'/api/tasks/{task["id"]}/events').json() == []
    assert db.tasks.insert_one.call_count == 1


@pytest.mark.parametrize("change", [
    {"title": "  "}, {"repository_url": "https://github.com.evil.test/x/y"},
    {"repository_url": "http://github.com/x/y"}, {"issue_number": 0},
    {"status": "completed"}, {"description": "x" * 10001},
])
def test_reject_invalid_input(api, change):
    client, db = api
    assert client.post("/api/tasks", json={**PAYLOAD, **change}).status_code == 422
    db.tasks.insert_one.assert_not_called()


def test_missing_and_malformed_id(api):
    client, _ = api
    assert client.get(f"/api/tasks/{uuid4()}").status_code == 404
    assert client.get("/api/tasks/not-a-uuid").status_code == 422


def test_pagination(api):
    client, db = api
    task = client.post("/api/tasks", json=PAYLOAD).json()
    db.tasks.find.return_value.sort.return_value.skip.return_value.limit.return_value = [task]
    db.tasks.count_documents.return_value = 3
    response = client.get("/api/tasks?limit=1&offset=1")
    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert response.json()["items"][0]["id"] == task["id"]
    db.tasks.find.assert_called_once_with({}, {"_id": 0})
    db.tasks.find.return_value.sort.return_value.skip.assert_called_once_with(1)
    assert client.get("/api/tasks?limit=101").status_code == 422
    assert client.get("/api/tasks?offset=-1").status_code == 422


def test_database_failure_is_sanitized(api):
    client, db = api
    db.tasks.insert_one.side_effect = ServerSelectionTimeoutError("secret-mongodb-uri")
    response = client.post("/api/tasks", json=PAYLOAD)
    assert response.status_code == 503
    assert "secret" not in response.text


def test_health(api):
    client, db = api
    assert client.get("/api/health/live").status_code == 200
    assert client.get("/api/health/ready").status_code == 200
    db.command.side_effect = ServerSelectionTimeoutError("offline")
    assert client.get("/api/health/ready").status_code == 503
    assert client.get("/api/health/live").status_code == 200


def test_cors(api):
    client, _ = api
    allowed = client.options("/api/tasks", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    rejected = client.options("/api/tasks", headers={"Origin": "https://unknown.test", "Access-Control-Request-Method": "POST"})
    assert rejected.status_code == 400
