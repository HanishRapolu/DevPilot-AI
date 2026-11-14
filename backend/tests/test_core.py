"""Synchronous checks also runnable where Windows cannot create asyncio socketpairs."""
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.tasks import create_task, get_events, get_task, list_tasks
from app.models import TaskCreate


def payload(**changes):
    return TaskCreate(**{"title": "Fix average", "repository_url": "https://github.com/example/demo.git/", **changes})


def test_atomic_create():
    db = MagicMock()
    task = create_task(payload(), db)
    stored = db.tasks.insert_one.call_args.args[0]
    assert stored["_id"] == task.id
    assert task.repository_url == "https://github.com/example/demo"
    assert stored["events"][0]["type"] == "task.created"
    assert task.status == "pending"


def test_retrieval_and_events():
    db = MagicMock()
    task = create_task(payload(), db)
    db.tasks.find_one.return_value = {"_id": task.id, **task.model_dump()}
    assert get_task(UUID(task.id), db) == task
    db.workflow_events.find.return_value.sort.return_value.limit.return_value = []
    assert get_events(UUID(task.id), db) == []


def test_missing_task():
    db = MagicMock()
    db.tasks.find_one.return_value = None
    with pytest.raises(HTTPException) as exc:
        get_task(uuid4(), db)
    assert exc.value.status_code == 404


def test_list_result():
    db = MagicMock()
    task = create_task(payload(), db)
    db.tasks.find.return_value.sort.return_value.skip.return_value.limit.return_value = [task.model_dump()]
    db.tasks.count_documents.return_value = 1
    page = list_tasks(20, 0, db)
    assert page.items == [task]
    assert page.total == 1


@pytest.mark.parametrize("changes", [{"title": " "}, {"issue_number": 0}, {"status": "done"}, {"repository_url": "https://github.com.evil/x/y"}])
def test_input_validation(changes):
    with pytest.raises(ValidationError):
        payload(**changes)
