import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=160)
    repository_url: str = Field(max_length=300)
    issue_number: int | None = Field(default=None, gt=0)
    description: str = Field(default="", max_length=10000)

    @field_validator("repository_url")
    @classmethod
    def github_repository(cls, value: str) -> str:
        value = value.rstrip("/")
        if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            raise ValueError("Use https://github.com/owner/repository")
        return value.removesuffix(".git")


class TaskEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: Literal["task.created"] = "task.created"
    message: str = "Task queued for execution."
    created_at: datetime = Field(default_factory=utc_now)


class Task(TaskCreate):
    status_history: list[dict] = Field(default_factory=lambda: [{"status": "pending", "timestamp": utc_now()}])
    workflow: dict = Field(default_factory=dict)
    approval: dict | None = None
    decision_claim: str | None = None
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: Literal["pending", "running", "awaiting_approval", "completed", "failed", "rejected"] = "pending"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    events: list[TaskEvent] = Field(default_factory=lambda: [TaskEvent()])


class TaskPage(BaseModel):
    items: list[Task]
    total: int
    limit: int
    offset: int
