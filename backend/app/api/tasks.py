from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ConfigDict
from app.models import utc_now
from pymongo.database import Database

from app.database import get_database
from app.models import Task, TaskCreate, TaskPage

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=Task, status_code=201)
def create_task(payload: TaskCreate, db: Database = Depends(get_database), request: Request = None) -> Task:
    expected = request.app.state.settings.github_repository.lower() if request else payload.repository_url.removeprefix("https://github.com/").lower()
    if not expected:
        raise HTTPException(503, "Configure GITHUB_REPOSITORY in backend/.env before starting a task.")
    if payload.repository_url.removeprefix("https://github.com/").lower() != expected:
        raise HTTPException(403, "Repository is not authorized in backend configuration.")
    if request and not payload.issue_number:
        raise HTTPException(422, "An issue number is required to start execution.")
    task = Task(**payload.model_dump())
    # Embedded events keep creation atomic on standalone MongoDB as well as Atlas.
    db.tasks.insert_one({"_id": task.id, **task.model_dump()})
    if request:
        request.app.state.jobs.submit(task.id)
    return task


@router.get("", response_model=TaskPage)
def list_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    db: Database = Depends(get_database),
) -> TaskPage:
    documents = db.tasks.find({}, {"_id": 0}).sort([("created_at", -1), ("_id", -1)]).skip(offset).limit(limit)
    return TaskPage(items=[Task.model_validate(d) for d in documents],
                    total=db.tasks.count_documents({}), limit=limit, offset=offset)


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: UUID, db: Database = Depends(get_database)) -> Task:
    document = db.tasks.find_one({"_id": str(task_id)})
    if document is None:
        raise HTTPException(404, "Task not found")
    document.pop("_id", None)
    return Task.model_validate(document)


@router.get("/{task_id}/events")
def get_events(task_id: UUID, db: Database = Depends(get_database)) -> list[dict]:
    get_task(task_id, db)
    return list(db.workflow_events.find({"task_id": str(task_id)}, {"_id": 0}).sort("timestamp", 1).limit(1000))


@router.get("/{task_id}/diff")
def get_diff(task_id: UUID, db: Database = Depends(get_database)):
    return get_task(task_id, db).workflow.get("diff") or {"patch": "", "files": []}


@router.get("/{task_id}/tests")
def get_tests(task_id: UUID, db: Database = Depends(get_database)):
    return get_task(task_id, db).workflow.get("test_results") or {"status": "not_run", "output": ""}


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def decide(task_id, payload, request, db, approved):
    get_task(task_id, db)
    updated = db.tasks.update_one({"_id": str(task_id), "status": "awaiting_approval",
        "approval.hash": payload.approval_hash, "decision_claim": None},
        {"$set": {"status": "running", "decision_claim": payload.approval_hash, "updated_at": utc_now()},
         "$push": {"status_history": {"status": "running", "timestamp": utc_now()}}})
    if updated.modified_count != 1:
        raise HTTPException(409, "Approval is stale, already submitted, or task is not awaiting approval.")
    request.app.state.jobs.submit(str(task_id), approved, payload.approval_hash)
    return {"status": "accepted"}


@router.post("/{task_id}/approve", status_code=202)
def approve(task_id: UUID, payload: Decision, request: Request, db: Database = Depends(get_database)):
    return decide(task_id, payload, request, db, True)


@router.post("/{task_id}/reject", status_code=202)
def reject(task_id: UUID, payload: Decision, request: Request, db: Database = Depends(get_database)):
    return decide(task_id, payload, request, db, False)
